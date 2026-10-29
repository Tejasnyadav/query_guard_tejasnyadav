from langsmith import traceable
import os

print("Tracing enabled:", os.getenv("LANGSMITH_TRACING"))
print("Project:", os.getenv("LANGSMITH_PROJECT"))
print("API key configured:", bool(os.getenv("LANGSMITH_API_KEY")))


@traceable
def test_trace():
    print("Sending a test trace to LangSmith")
    return {"status": "success", "message": "LangSmith connection works!"}


result = test_trace()
print("Result:", result)