"""Safe demonstration workflows: they return guidance and never perform external actions."""


def _reply(label: str):
    def run(request_text: str):
        return {
            "message": f"{label} workflow completed. This demonstration provides a response only; it does not change external systems.",
            "request_summary": request_text[:280],
        }
    return run


WORKFLOWS = {
    "technical_support": _reply("Technical support"),
    "general_information": _reply("General information"),
    "data_analysis": _reply("Data analysis"),
    "software_development": _reply("Software development"),
    "account_management": _reply("Account management"),
    "task_automation": _reply("Task automation"),
}