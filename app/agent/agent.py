import uuid as _uuid

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from app.agent.tools import (
    ingest_file,
    get_job_status,
    query_rag,
    list_documents,
    summarize_document,
    set_agent_user_id,
)
from app.observability.logging import get_logger

log = get_logger()

AGENT_SYSTEM_PROMPT = """You are an intelligent document assistant for MasterCRM.

You have access to tools that let you process files and answer questions about them.

When asked to process a file and answer questions:
1. Call ingest_file to start processing. Note the job_id.
2. Call get_job_status repeatedly (every 5 seconds) until status is COMPLETED.
3. If status is FAILED or FAILED_PERMANENT, report the error and stop.
4. Once COMPLETED, call summarize_document or query_rag as the user requested.

When asked a question without specifying a file:
1. Call list_documents to see what is available.
2. If relevant documents exist, call query_rag.
3. If no documents exist, tell the user to upload files first.

Always cite your sources. Always report errors clearly.
"""

_agent = Agent(
    model="gemini-2.0-flash",
    name="geminirag_agent",
    instruction=AGENT_SYSTEM_PROMPT,
    tools=[ingest_file, get_job_status, query_rag, list_documents, summarize_document],
)

_session_service = InMemorySessionService()
_runner = Runner(
    app_name="geminirag",
    agent=_agent,
    session_service=_session_service,
)


async def run_agent(message: str, user_id: str, session_id: str | None = None) -> dict:
    """Run the ADK agent and return the final text response with tool call log."""
    if session_id is None:
        session_id = str(_uuid.uuid4())

    try:
        await _session_service.create_session(
            app_name="geminirag",
            user_id=user_id,
            session_id=session_id,
        )
    except Exception:
        pass  # Session already exists for multi-turn conversations

    set_agent_user_id(user_id)

    tool_names: list[str] = []
    final_text = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    async for event in _runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=message)],
        ),
    ):
        for fc in event.get_function_calls():
            tool_names.append(fc.name)

        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    final_text += part.text

        if event.usage_metadata:
            try:
                prompt_tokens = getattr(event.usage_metadata, "prompt_token_count", None)
                completion_tokens = getattr(event.usage_metadata, "candidates_token_count", None)
            except Exception:
                pass

    log.info(
        "agent_run_complete",
        user_id=user_id,
        session_id=session_id,
        tool_call_count=len(tool_names),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )

    return {
        "response": final_text,
        "tool_calls_made": tool_names,
        "session_id": session_id,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
