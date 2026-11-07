"""Human review state transitions."""


class ReviewError(ValueError):
    pass


def resolve_review(record: dict, action: str, feedback: str, execute):
    if record["status"] != "pending_review":
        raise ReviewError("This request is not awaiting review.")
    if action == "approve":
        if record["category"] in (None, "UNKNOWN") or not record["workflow"]:
            raise ReviewError("An unknown or unsupported intent cannot be approved for automatic execution.")
        result = execute(record["workflow"], record["request_text"])
        return {"status": "completed", "result": result, "reviewer_feedback": feedback}
    if action == "reject":
        return {"status": "rejected", "reviewer_feedback": feedback}
    if action == "clarify":
        return {"status": "awaiting_clarification", "reviewer_feedback": feedback}
    raise ReviewError("Action must be approve, reject, or clarify.")