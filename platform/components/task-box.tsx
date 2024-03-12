"use client";

import ThumbsUpAndDown from "@/components/thumbs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { useToast } from "@/components/ui/use-toast";
import { Event, EventDefinition } from "@/models/events";
import { Task, TaskWithEvents } from "@/models/tasks";
import { navigationStateStore } from "@/store/store";
import { useUser } from "@propelauth/nextjs/client";
import { Check, Trash } from "lucide-react";
import React from "react";
import ReactMarkdown from "react-markdown";

const InteractiveEventBadge = ({
  event,
  task,
  setTask,
}: {
  event: Event;
  task: TaskWithEvents;
  setTask: (task: TaskWithEvents) => void;
}) => {
  const { accessToken } = useUser();

  const selectedProject = navigationStateStore(
    (state) => state.selectedProject,
  );
  // Find the event definition in the project settings
  const eventDefinition: EventDefinition =
    selectedProject?.settings?.events[event.event_name];
  const { toast } = useToast();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger>
        <HoverCard openDelay={50} closeDelay={50}>
          <HoverCardTrigger>
            <Badge variant="outline" className=" hover:border-green-500">
              {event.event_name}
            </Badge>
          </HoverCardTrigger>
          <HoverCardContent side="top" className="text-sm text-left">
            <h2 className="font-bold">{event.event_name}</h2>
            <p>Source: {event.source}</p>
            <p>{eventDefinition.description}</p>
          </HoverCardContent>
        </HoverCard>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem>
          <Check
            className="w-4 h-4 mr-2"
            onClick={() => {
              toast({
                title: "Coming soon 🛠️",
                description:
                  "This feature is still being developed. Your changes were not be saved.",
              });
            }}
          />{" "}
          Confirm
        </DropdownMenuItem>
        <DropdownMenuItem
          className="text-red-500"
          onClick={async () => {
            setTask({
              ...task,
              events: task.events.filter(
                (e) => e.event_name !== event.event_name,
              ),
            });
            // toast({
            //   title: "Coming soon 🛠️",
            //   description:
            //     "This feature is still being developed. Your changes were not be saved.",
            // });

            // Call the API to remove the event from the task
            const response = await fetch(`/api/tasks/${task.id}/remove-event`, {
              method: "POST",
              headers: {
                Authorization: "Bearer " + accessToken,
                "Content-Type": "application/json",
              },
              body: JSON.stringify({
                event_name: event.event_name,
              }),
            });
          }}
        >
          <Trash className="w-4 h-4 mr-2" /> Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

const AddEvent = ({
  task,
  setTask,
}: {
  task: TaskWithEvents;
  setTask: (task: TaskWithEvents) => void;
}) => {
  if (!task) {
    return <></>;
  }
  const { accessToken } = useUser();
  const events = task.events;
  const selectedProject = navigationStateStore(
    (state) => state.selectedProject,
  );
  const project_id = selectedProject?.id;

  // Project events is an object : {event_name: EventDefinition}
  const projectEvents: Record<string, EventDefinition> =
    selectedProject?.settings?.events || null;

  if (!projectEvents) {
    return <></>;
  }

  const eventsNotInTask = Object.entries(projectEvents).filter(
    ([event_name, event]) => {
      // If the event is already in the task, don't show it
      return !events?.some((e) => e.event_name === event_name);
    },
  );
  if (eventsNotInTask.length === 0) {
    return <></>;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger>
        <Badge variant="outline" className=" hover:border-green-500">
          +
        </Badge>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {Object.entries(projectEvents).map(([event_name, event]) => {
          // If the event is already in the task, don't show it
          if (events?.some((e) => e.event_name === event_name)) {
            return <></>;
          }

          return (
            <HoverCard openDelay={50} closeDelay={50}>
              <HoverCardTrigger>
                <DropdownMenuItem
                  key={event_name}
                  onClick={async () => {
                    // Adds the event to the task and updates the task
                    setTask({
                      ...task,
                      events: [
                        ...task.events,
                        {
                          id: "0", // TODO: generate a real id
                          created_at: Math.floor(Date.now() / 1000),
                          task_id: task.id,
                          session_id: task.session_id,
                          project_id: task.project_id,
                          event_name: event_name,
                          source: "owner",
                        },
                      ],
                    });
                    // Call the API to ad the event to the task
                    const response = await fetch(
                      `/api/tasks/${task.id}/add-event`,
                      {
                        method: "POST",
                        headers: {
                          Authorization: "Bearer " + accessToken,
                          "Content-Type": "application/json",
                        },
                        body: JSON.stringify({
                          event: event,
                        }),
                      },
                    );

                    // TODO : Use the response to update the task
                  }}
                >
                  {event_name}
                </DropdownMenuItem>
              </HoverCardTrigger>
              <HoverCardContent side="right" className="text-sm">
                <h2 className="font-bold">{event_name}</h2>
                <p>{event.description}</p>
              </HoverCardContent>
            </HoverCard>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

const TaskBox = ({
  task,
  setTask,
  setFlag,
}: {
  task: TaskWithEvents;
  setTask: (task: Task) => void;
  setFlag: (flag: string) => void;
}) => {
  return (
    <div className="mb-2 p-1 border border-gray-800 rounded">
      <div className="flex justify-between align-top">
        <div className="space-x-2">
          {task?.events?.map((event) => {
            return (
              <InteractiveEventBadge
                key={event.event_name}
                event={event}
                task={task}
                setTask={setTask}
              ></InteractiveEventBadge>
            );
          })}
          <AddEvent task={task} setTask={setTask} />
        </div>
        <ThumbsUpAndDown
          task={task}
          setTask={(task: Task | null) => {
            setTask(task as TaskWithEvents);
          }}
          flag={task.flag}
          setFlag={setFlag}
          key={task.id}
        ></ThumbsUpAndDown>
      </div>
      <div>
        <div className="text-muted-foreground font-semibold mx-2">User:</div>
        <div className="whitespace-pre-wrap">
          {task.input && (
            <ReactMarkdown className="mb-2 mx-2">{task.input}</ReactMarkdown>
          )}
        </div>
        <div className="text-muted-foreground font-semibold mx-2">
          Assistant:
        </div>
        <div className="whitespace-pre-wrap">
          {task.output && (
            <ReactMarkdown className="mb-2 mx-2">{task.output}</ReactMarkdown>
          )}
        </div>
      </div>
      <Collapsible>
        <CollapsibleTrigger>
          <Button variant="link">{">"} View Raw Task Data</Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <pre className="whitespace-pre-wrap mx-2">
            {JSON.stringify(task, null, 2)}
          </pre>
        </CollapsibleContent>
      </Collapsible>
      <div>
        {task.metadata &&
          Object.entries(task.metadata)
            .sort(
              // sort by alphabetic key
              ([key1, value1], [key2, value2]) => {
                if (key1 < key2) {
                  return -1;
                }
                if (key1 > key2) {
                  return 1;
                }
                return 0;
              },
            )
            .map(([key, value]) => {
              // console.log("key :", key);
              if (typeof value === "string" || typeof value === "number") {
                return (
                  <Badge variant="outline" className="mx-2 text-xs font-normal">
                    <p key={key}>
                      {key}: {value}
                    </p>
                  </Badge>
                );
              }
            })}
      </div>
    </div>
  );
};

export default TaskBox;
export { TaskBox, AddEvent, InteractiveEventBadge };
