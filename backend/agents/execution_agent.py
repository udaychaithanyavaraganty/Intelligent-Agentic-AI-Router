"""Executes only locally registered, predefined workflows."""

from backend.workflows import WORKFLOWS


class ExecutionError(ValueError):
    pass


def execute_workflow(workflow: str, request_text: str) -> dict:
    handler = WORKFLOWS.get(workflow)
    if handler is None:
        raise ExecutionError("Workflow is not in the local execution registry.")
    return handler(request_text)