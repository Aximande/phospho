import requests

response = requests.get('https://api.phospho.com')
print(response.status_code)
print(response.text)
