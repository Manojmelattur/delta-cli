def test_except():
    from fastapi import HTTPException
    try:
        raise HTTPException(404, "Task not found")
    except HTTPException:
        print("Caught HTTPException")
    except Exception as e:
        print("Caught generic exception")

test_except()
