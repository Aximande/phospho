import time
from typing import Dict, List, Literal, Optional

from loguru import logger

from app.core import config
from app.db.models import Eval, Event, EventDefinition, Recipe, LlmCall, Task
from app.db.mongo import get_mongo_db
from app.services.data import fetch_previous_tasks
from app.services.projects import get_project_by_id

# from app.services.topics import extract_topics  # TODO
from app.services.webhook import trigger_webhook
from phospho import lab
from phospho.models import ResultType, ScoreRange, SentimentObject, JobResult

from app.api.v1.models.pipelines import PipelineResults

from app.services.sentiment_analysis import run_sentiment_and_language_analysis

from phospho.models import Project
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto import Random
import os
import base64


class EventConfig(lab.JobConfig):
    event_name: str
    event_description: str


async def run_event_detection_pipeline(
    workload: lab.Workload, tasks: List[Task]
) -> Dict[str, List[Event]]:
    """
    webhook_url and webhook_headers are optional parameters of the metadata
    `webhook_url` is the URL to trigger when an event is detected. If None, no webhook is triggered.
    job_id can be found for each job of the workload in the job metadata
    """
    mongo_db = await get_mongo_db()
    # Create the list of messages
    messages = []
    events_per_task = {}

    for task in tasks:
        message = lab.Message.from_task(task=task, metadata={"task": task})
        messages.append(message)

    await workload.async_run(
        messages=messages,
        executor_type="parallel_jobs",
    )

    # Display the workload results
    logger.info(f"Workload results : {workload.results}")

    # Iter over the results
    for message in messages:
        results = workload.results.get(message.id, {})
        logger.debug(f"Results for message {message.id} : {results}")

        events_per_task[message.metadata["task"].id] = []

        for event_name, result in results.items():
            # event_name is the primary key of the table
            # Get the `job_id`from the job metadata, which is a dump of the event definition
            webhook_url = workload.jobs[event_name].metadata.get("webhook_url", None)
            webhook_headers = workload.jobs[event_name].metadata.get(
                "webhook_headers", None
            )

            # Store the LLM call in the database
            metadata = result.metadata
            llm_call = metadata.get("llm_call", None)
            if llm_call is not None:
                llm_call_obj = LlmCall(
                    **llm_call,
                    org_id=task.org_id,
                    task_id=message.metadata["task"].id,
                    recipe_id=result.job_metadata.get("recipe_id"),
                )
                mongo_db["llm_calls"].insert_one(llm_call_obj.model_dump())
            else:
                logger.warning(f"No LLM call detected for event {event_name}")

            # When the event is detected, result is True
            if result.value:
                logger.info(
                    f"Event {event_name} detected for task {message.metadata['task'].id}"
                )
                # Get back the event definition from the job metadata
                metadata = workload.jobs[result.job_id].metadata
                event = EventDefinition.model_validate(metadata)
                # Push event to db
                detected_event_data = Event(
                    event_name=event_name,
                    # Events detected at the session scope are not linked to a task
                    task_id=message.metadata["task"].id,
                    session_id=message.metadata["task"].session_id,
                    project_id=message.metadata["task"].project_id,
                    source=result.metadata.get("evaluation_source", "phospho-unknown"),
                    webhook=event.webhook,
                    org_id=message.metadata["task"].org_id,
                    event_definition=event,
                    task=message.metadata["task"],
                    score_range=result.metadata.get("score_range", None),
                )

                # Update the task object with the event
                await mongo_db["tasks"].update_one(
                    {
                        "id": message.metadata["task"].id,
                        "project_id": message.metadata["task"].project_id,
                    },
                    # Add the event to the list of events
                    {"$addToSet": {"events": detected_event_data.model_dump()}},
                )
                if webhook_url is not None:
                    await trigger_webhook(
                        url=webhook_url,
                        json=detected_event_data.model_dump(),
                        headers=webhook_headers,
                    )

                # Update the Events collection with the new event
                await mongo_db["events"].insert_one(detected_event_data.model_dump())

                events_per_task[message.metadata["task"].id].append(detected_event_data)

            else:
                logger.info(
                    f"Event {event_name} NOT detected for task {message.metadata['task'].id}"
                )
                # Handle the case where the event is not detected, but was previously detected
                # We need to remove the event from the task document

                await mongo_db["tasks"].update_one(
                    {
                        "id": message.metadata["task"].id,
                        "project_id": message.metadata["task"].project_id,
                    },
                    # Remove the event from the list of events
                    {"$pull": {"events": {"event_name": event_name}}},
                )

                # Try to delete the event from the Event collection
                await mongo_db["events"].delete_one(
                    {"task_id": message.metadata["task"].id, "event_name": event_name}
                )

            # Save the prediction
            result.task_id = message.metadata["task"].id
            if result.job_metadata.get("recipe_id") is None:
                logger.error(f"No recipe_id found for event {event_name}.")
            mongo_db["job_results"].insert_one(result.model_dump())

    return events_per_task


async def task_event_detection_pipeline(
    task: Task, save_task: bool = False
) -> List[Event]:
    """
    Run the event detection pipeline for a given task
    """
    logger.info(f"Run the event detection pipeline for task {task.id}")
    mongo_db = await get_mongo_db()

    # Get the data of all the tasks before task[task_id]
    previous_tasks = await fetch_previous_tasks(task.id)
    task_data = previous_tasks[-1]
    if len(previous_tasks) > 1:
        task_context = previous_tasks[:-1]
    else:
        task_context = []

    # Get the project settings
    project_id = task_data.project_id
    project = await get_project_by_id(project_id)
    if project.settings is None:
        logger.warning(f"Project with id {project_id} has no settings")
        return []
    # Convert to the proper lab project object
    # TODO : Normalize the project definition by storing all db models in the phospho module
    # and importing models from the phospho module
    workload = lab.Workload.from_phospho_project_config(project)
    logger.debug(f"Workload for project {project_id} : {workload}")

    # events_per_task = await run_event_detection_pipeline(workload=workload, tasks=[task])

    message = lab.Message.from_task(task=task_data, previous_tasks=task_context)
    latest_message_id = message.id
    await workload.async_run(
        messages=[message],
        executor_type="parallel_jobs",
    )

    # Check the results of the workload
    message_results = workload.results.get(latest_message_id, [])
    detected_events = []
    for event_name, result in message_results.items():
        # Store the LLM call in the database
        metadata = result.metadata
        llm_call = metadata.get("llm_call", None)
        if llm_call is not None:
            llm_call_obj = LlmCall(
                **llm_call,
                org_id=task_data.org_id,
                task_id=task.id,
                recipe_id=result.job_metadata.get("recipe_id"),
                project_id=project_id,
            )
            mongo_db["llm_calls"].insert_one(llm_call_obj.model_dump())
        else:
            logger.warning(f"No LLM call detected for event {event_name}")

        # When the event is detected, result is True
        if result.value:
            logger.info(f"Event {event_name} detected for task {task_data.id}")
            # Get back the event definition from the job metadata
            metadata = workload.jobs[result.job_id].metadata
            event_definition = EventDefinition.model_validate(metadata)
            # Push event to db
            detected_event_data = Event(
                event_name=event_name,
                # Events detected at the session scope are not linked to a task
                task_id=task_data.id,
                session_id=task_data.session_id,
                project_id=project_id,
                source=result.metadata.get("evaluation_source", "phospho-unknown"),
                webhook=event_definition.webhook,
                org_id=task_data.org_id,
                event_definition=event_definition,
                task=task_data if save_task else None,
                score_range=result.metadata.get("score_range", None),
            )
            detected_events.append(detected_event_data)
            # Update the task object with the event
            if save_task:
                mongo_db["tasks"].update_many(
                    {"id": task.id, "project_id": task.project_id},
                    # Add the event to the list of events
                    {"$push": {"events": detected_event_data.model_dump()}},
                )
            # Trigger the webhook if it exists
            if event_definition.webhook is not None:
                await trigger_webhook(
                    url=event_definition.webhook,
                    json=detected_event_data.model_dump(),
                    headers=event_definition.webhook_headers,
                )

        result.task_id = task.id
        if result.job_metadata.get("recipe_id") is None:
            logger.error(f"No recipe_id found for event {event_name}")

        mongo_db["job_results"].insert_one(result.model_dump())

    if len(detected_events) > 0:
        try:
            mongo_db["events"].insert_many(
                [event.model_dump() for event in detected_events]
            )
        except Exception as e:
            error_mesagge = f"Error saving detected events to the database: {e}"
            logger.error(error_mesagge)

    return detected_events


async def task_scoring_pipeline(
    task: Task, save_task: bool = True
) -> Optional[Literal["success", "failure"]]:
    """
    Run the task scoring pipeline for a given task
    """
    logger.debug(f"Run the task scoring pipeline for task {task.id}")
    mongo_db = await get_mongo_db()

    # We want 50/50 success and failure examples
    nb_success = int(config.FEW_SHOT_MAX_NUMBER_OF_EXAMPLES / 2)
    nb_failure = int(config.FEW_SHOT_MAX_NUMBER_OF_EXAMPLES / 2)

    PHOSPHO_EVAL_MODELS_NAMES = ["phospho", "phospho-4"]

    # Get the user evals from the db
    successful_examples_tasks = (
        await mongo_db["evals"]
        .aggregate(
            [
                {
                    "$match": {
                        "project_id": task.project_id,
                        "source": {"$nin": PHOSPHO_EVAL_MODELS_NAMES},
                        "value": "success",
                    }
                },
                {"$sort": {"created_at": -1}},
                {"$limit": nb_success},
                {
                    "$lookup": {
                        "from": "tasks",
                        "localField": "task_id",
                        "foreignField": "id",
                        "as": "task",
                    }
                },
                {"$unwind": "$task"},
                {
                    "$addFields": {
                        "flag": "$value",
                        "output": "$task.output",
                        "input": "$task.input",
                    }
                },
                {"$project": {"input": 1, "output": 1, "flag": 1}},
            ]
        )
        .to_list(length=None)
    )
    logger.debug(f"Nb of successful examples: {len(successful_examples_tasks)}")

    # Get the failure examples
    unsuccessful_examples_tasks = (
        await mongo_db["evals"]
        .aggregate(
            [
                {
                    "$match": {
                        "project_id": task.project_id,
                        "source": {"$nin": PHOSPHO_EVAL_MODELS_NAMES},
                        "value": "failure",
                    }
                },
                {"$sort": {"created_at": -1}},
                {"$limit": nb_failure},
                {
                    "$lookup": {
                        "from": "tasks",
                        "localField": "task_id",
                        "foreignField": "id",
                        "as": "task",
                    }
                },
                {"$unwind": "$task"},
                {
                    "$addFields": {
                        "flag": "$value",
                        "output": "$task.output",
                        "input": "$task.input",
                    }
                },
                {"$project": {"input": 1, "output": 1, "flag": 1}},
            ]
        )
        .to_list(length=None)
    )
    logger.debug(f"Nb of failure examples: {len(unsuccessful_examples_tasks)}")

    # Get the Task's system prompt
    if task.metadata is not None:
        system_prompt = task.metadata.get("system_prompt", None)
    else:
        system_prompt = None

    # Call the eval function
    # Create the phospho workload
    workload = lab.Workload()
    workload.add_job(
        lab.Job(
            id="evaluate_task",
            job_function=lab.job_library.evaluate_task,
            metadata={
                "recipe_id": "generic_evaluation",
                "recipe_type": "evaluation",
            },
        )
    )
    workload.org_id = task.org_id
    workload.project_id = task.project_id

    # Convert to a list of messages
    message = lab.Message.from_task(
        task=task,
        metadata={
            "successful_examples": successful_examples_tasks,
            "unsuccessful_examples": unsuccessful_examples_tasks,
            "system_prompt": system_prompt,
        },
    )
    await workload.async_run(messages=[message], executor_type="sequential")
    # Check the results of the workload
    if workload.results is None:
        logger.error("Worlkload.results is None")
        return None

    job_result = workload.results.get(message.id, {}).get("evaluate_task", None)
    if job_result is None:
        logger.error("Job result in workload is None")
        return None

    flag = job_result.value
    llm_call = job_result.metadata.get("llm_call", None)
    if llm_call is not None:
        llm_call_obj = LlmCall(
            **llm_call,
            org_id=task.org_id,
            task_id=task.id,
            recipe_id=job_result.job_metadata.get("recipe_id"),
            project_id=task.project_id,
        )
        mongo_db["llm_calls"].insert_one(llm_call_obj.model_dump())

    logger.debug(f"Flag for task {task.id} : {flag}")
    # Create the Evaluation object and store it in the db
    evaluation_data = Eval(
        project_id=task.project_id,
        session_id=task.session_id,
        task_id=task.id,
        value=flag,
        source=config.EVALUATION_SOURCE,
        test_id=task.test_id,
        org_id=task.org_id,
        task=task if not save_task else None,
    )
    mongo_db["evals"].insert_one(evaluation_data.model_dump())
    # Save the prediction
    job_result.task_id = task.id
    mongo_db["job_results"].insert_one(job_result.model_dump())

    # Update the task object if the flag is None (no previous evaluation)
    if save_task:
        task_in_db = await mongo_db["tasks"].find_one({"id": task.id})
        if task_in_db.get("flag") is None:
            mongo_db["tasks"].update_one(
                {"id": task.id},
                {
                    "$set": {
                        "flag": flag,
                        "last_eval": evaluation_data.model_dump(),
                        "evaluation_source": config.EVALUATION_SOURCE,
                    }
                },
            )
    return flag


# async def topic_extraction_pipeline(task_id: str) -> None:
#     mongo_db = await get_mongo_db()

#     task_data = await mongo_db["tasks"].find_one({"id": task_id})

#     task_input = task_data.get("input", None)
#     task_output = task_data.get("output", None)

#     # Build the text to extract topics from
#     text_input = f"{task_input} {task_output}"

#     detected_topics = extract_topics(text_input)

#     if len(detected_topics) == 0:
#         logger.debug(f"No topics detected for task {task_id}")
#         # Stop the execution of the pipeline
#         return

#     logger.debug(f"Detected topics for task {task_id} : {detected_topics}")

#     # Save the detected topics in the MongoDB document
#     update_result = await mongo_db["tasks"].update_one(
#         {"id": task_id}, {"$set": {"topics": detected_topics}}
#     )

#     # Check if the operation matched and modified any document
#     if update_result.matched_count == 0:
#         raise ValueError(f"Task with id {task_id} not found in the database.")

#     elif update_result.modified_count == 0:
#         logger.warning(
#             "Document found, but no changes were made (it might already have the same topics data)."
#         )

#     else:
#         # The document was not changed in the DB
#         logger.info(f"Detected topics for task {task_id} saved in the database")


async def task_main_pipeline(task: Task, save_task: bool = True) -> PipelineResults:
    """
    Main pipeline to run on a task.
    - Event detection
    - Evaluate task success/failure
    - Language detection
    - Sentiment analysis
    """

    # Get the starting time of the pipeline
    start_time = time.time()
    logger.info(f"Starting main pipeline for task {task.id}")

    # For now, do things sequentially

    # Do the event detection
    if task.test_id is None:
        # Run the event detection pipeline
        events = await task_event_detection_pipeline(task, save_task=save_task)
        # Run sentiment analysis on the user input
        sentiment_object, language = await sentiment_and_language_analysis_pipeline(
            task
        )

    # Do the session scoring -> success, failure
    mongo_db = await get_mongo_db()

    if save_task:
        task_in_db = await mongo_db["tasks"].find_one({"id": task.id})
        if task_in_db.get("flag") is None:
            flag = await task_scoring_pipeline(task, save_task=save_task)
        else:
            flag = task_in_db.get("flag")
    else:
        flag = await task_scoring_pipeline(task, save_task=save_task)

    # Optional: later add the moderation pipeline on input and outputs

    # Do the topic extraction
    # await topic_extraction_pipeline(task_id)

    # Log the completion of the pipeline and the time it took
    logger.info(
        f"Main pipeline completed in {time.time() - start_time:.2f} seconds for task {task.id}"
    )

    return PipelineResults(
        events=events,
        flag=flag,
        language=language,
        sentiment=sentiment_object,
    )


async def messages_main_pipeline(
    project_id: str, messages: List[lab.Message]
) -> PipelineResults:
    """
    Main pipeline to run on a list of messages.
    We expect the messages to be in chronological order.
    Only the last message will be used for the event detection.
    The previous messages will be used as context.

    - Event detection
    """
    mongo_db = await get_mongo_db()
    project = await get_project_by_id(project_id)

    if project.settings is None:
        logger.warning(f"Project with id {project_id} has no settings")
        return []
    workload = lab.Workload.from_phospho_project_config(project)
    message = lab.Message(
        id="single_message",
        role=messages[-1].role,
        content=messages[-1].content,
        metadata=messages[-1].metadata,
        previous_messages=messages[:-1],
    )
    await workload.async_run(messages=[message], executor_type="parallel_jobs")
    events: List[Event] = []
    for event_name, result in workload.results["single_message"].items():
        # We actually ran the pipeline on a single message, with
        # the previous messages as context
        logger.debug(f"Result for {event_name}: {result.value}")
        if result.value is True:
            metadata = workload.jobs[result.recipe_id].metadata
            event = EventDefinition(**metadata)
            detected_event_data = Event(
                event_name=event_name,
                project_id=project_id,
                source=result.metadata.get("source", "phospho-unknown"),
                webhook=event.webhook,
                event_definition=event,
                messages=messages,
            )
            events.append(detected_event_data)

            if event.webhook is not None:
                await trigger_webhook(
                    url=event.webhook,
                    json=detected_event_data.model_dump(),
                    headers=event.webhook_headers,
                )

        # Save the prediction
        if result.job_metadata.get("recipe_id") is None:
            logger.error(f"No recipe_id found for event {event_name}")

        mongo_db["job_results"].insert_one(result.model_dump())

    # Push the events to the database
    if len(events) > 0:
        try:
            mongo_db["events"].insert_many([event.model_dump() for event in events])
        except Exception as e:
            error_mesagge = f"Error saving detected events to the database: {e}"
            logger.error(error_mesagge)

    return PipelineResults(
        events=events,
        flag=None,
    )


async def recipe_pipeline(tasks: List[Task], recipe: Recipe):
    """
    Run a job on a task
    """

    if recipe.recipe_type == "event_detection":
        logger.info(
            f"PIPELINE: Running event detection job {recipe.id} on {len(tasks)} tasks"
        )

        workload = lab.Workload.from_phospho_recipe(recipe)
        workload.org_id = recipe.org_id
        workload.project_id = recipe.project_id

        # display the jobs
        logger.info(f"Jobs for the workload: {workload.jobs}")

        await run_event_detection_pipeline(workload, tasks)

    else:
        raise ValueError(f"Job type {recipe.recipe_type} not supported")


async def sentiment_and_language_analysis_pipeline(
    task: Task,
) -> tuple[SentimentObject, Optional[str]]:
    """
    Run the sentiment analysis on the input of a task
    """
    mongo_db = await get_mongo_db()
    project = await get_project_by_id(task.project_id)

    # Default values
    score_threshold = 0.3
    magnitude_threshold = 0.6
    # Try to replace with project settings
    if project.settings.sentiment_threshold is not None:
        if project.settings.sentiment_threshold.score is not None:
            score_threshold = project.settings.sentiment_threshold.score
        else:
            mongo_db["projects"].update_one(
                {"id": task.project_id},
                {
                    "$set": {
                        "settings.sentiment_threshold.score": 0.3,
                    }
                },
            )

        if project.settings.sentiment_threshold.magnitude is not None:
            magnitude_threshold = project.settings.sentiment_threshold.magnitude
        else:
            mongo_db["projects"].update_one(
                {"id": task.project_id},
                {
                    "$set": {
                        "settings.sentiment_threshold.magnitude": 0.6,
                    }
                },
            )
    else:
        mongo_db["projects"].update_one(
            {"id": task.project_id},
            {
                "$set": {
                    "settings.sentiment_threshold": {
                        "score": 0.3,
                        "magnitude": 0.6,
                    }
                }
            },
        )

    sentiment_object, language = await run_sentiment_and_language_analysis(
        task.input, score_threshold, magnitude_threshold
    )

    await mongo_db["tasks"].update_one(
        {
            "id": task.id,
            "project_id": task.project_id,
        },
        {
            "$set": {
                "sentiment": sentiment_object.model_dump(),
                "language": language,
                "metadata.sentiment_score": sentiment_object.score,
                "metadata.sentiment_magnitude": sentiment_object.magnitude,
                "metadata.sentiment_label": sentiment_object.label,
                "metadata.language": language,
            }
        },
    )

    jobresult = JobResult(
        org_id=task.org_id,
        project_id=task.project_id,
        job_id="sentiment_analysis",
        value=sentiment_object.model_dump(),
        result_type=ResultType.dict,
        metadata={
            "input": task.input,
        },
    )

    mongo_db["job_results"].insert_one(jobresult.model_dump())

    logger.info(f"Sentiment analysis for task {task.id} : {sentiment_object}")

    return sentiment_object, language


async def store_opentelemetry_data_in_db(
    open_telemetry_data: dict, project_id: str, org_id: str
):
    """
    Store the opentelemetry data in the database
    """
    mongo_db = await get_mongo_db()

    # Store the data in the database
    mongo_db["opentelemetry"].insert_one(
        {
            "org_id": org_id,
            "project_id": project_id,
            "open_telemetry_data": open_telemetry_data,
        }
    )
    logger.info("Opentelemetry data stored in the database")
    return {"status": "ok"}


async def get_last_langsmith_extract(
    project_id: str,
):
    """
    Get the last Langsmith extract for a project
    """
    mongo_db = await get_mongo_db()

    project = await mongo_db["projects"].find_one(
        {"id": project_id},
    )

    try:
        project_validated = Project.model_validate(project)
    except Exception as e:
        logger.error(f"Error validating project data: {e}")
        return None

    return project_validated.settings.last_langsmith_extract


async def change_last_langsmith_extract(
    project_id: str,
    new_last_extract_date: str,
):
    """
    Change the last Langsmith extract for a project
    """
    mongo_db = await get_mongo_db()

    await mongo_db["projects"].update_one(
        {"id": project_id},
        {"$set": {"settings.last_langsmith_extract": new_last_extract_date}},
    )


async def encrypt_and_store_langsmith_credentials(
    project_id: str,
    langsmith_api_key: str,
    langsmith_project_name: str,
):
    """
    Store the encrypted Langsmith credentials in the database
    """

    mongo_db = await get_mongo_db()

    encryption_key = os.getenv("EXTRACTOR_ENCRYPTION_KEY")
    api_key_as_bytes = langsmith_api_key.encode("utf-8")

    # Encrypt the credentials
    key = SHA256.new(
        encryption_key.encode("utf-8")
    ).digest()  # use SHA-256 over our key to get a proper-sized AES key

    IV = Random.new().read(AES.block_size)  # generate IV
    encryptor = AES.new(key, AES.MODE_CBC, IV)
    padding = (
        AES.block_size - len(api_key_as_bytes) % AES.block_size
    )  # calculate needed padding
    api_key_as_bytes += bytes([padding]) * padding
    data = IV + encryptor.encrypt(
        api_key_as_bytes
    )  # store the IV at the beginning and encrypt

    # Store the encrypted credentials in the database
    await mongo_db["keys"].update_one(
        {"project_id": project_id},
        {
            "$set": {
                "langsmith_api_key": base64.b64encode(data).decode("latin-1"),
                "langsmith_project_name": langsmith_project_name,
            },
        },
        upsert=True,
    )
