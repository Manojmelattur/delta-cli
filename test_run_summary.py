import requests
res = requests.get('http://localhost:8000/api/runs/backtest_20260731_143539/summary')
print(res.status_code)
print(res.text)
