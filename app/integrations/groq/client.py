from __future__ import annotations

import logging

from langchain_groq import ChatGroq

from app.models.incident import IncidentAnalysis, ParcleDocument
from app.prompts.incident import ANALYSIS_SYSTEM_PROMPT, ENTERPRO_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class GroqIntegrationError(RuntimeError):
    """Raised when Groq cannot complete an incident task."""


class GroqIncidentAnalyzer:
    def __init__(self, api_key: str | None, model: str):
        self.api_key = api_key
        self.model = model

    def _llm(self) -> ChatGroq:
        if not self.api_key:
            raise GroqIntegrationError("GROQ_API_KEY is not configured")
        return ChatGroq(api_key=self.api_key, model=self.model, temperature=0)

    def analyze(self, incident: str, documents: list[ParcleDocument]) -> IncidentAnalysis:
        context = "\n\n".join(
            f"[{doc.title}] ({doc.reference or 'no reference'})\n{doc.content}" for doc in documents
        ) or "No documentation was returned by Parcle. Clearly account for this uncertainty."
        try:
            structured_llm = self._llm().with_structured_output(IncidentAnalysis)
            return structured_llm.invoke(
                [("system", ANALYSIS_SYSTEM_PROMPT), ("human", f"Incident:\n{incident}\n\nDocumentation:\n{context}")]
            )
        except Exception as exc:  # provider exceptions vary by SDK version
            logger.exception("Groq incident analysis failed")
            raise GroqIntegrationError(f"Groq incident analysis failed: {exc}") from exc

    def generate_enterpro_prompt(
        self, incident: str, analysis: IncidentAnalysis, documents: list[ParcleDocument]
    ) -> str:
        references = ", ".join(filter(None, (doc.reference for doc in documents))) or "None"
        try:
            response = self._llm().invoke(
                [
                    ("system", ENTERPRO_SYSTEM_PROMPT),
                    (
                        "human",
                        f"Incident: {incident}\nAnalysis: {analysis.model_dump_json(indent=2)}\n"
                        f"Documentation references: {references}",
                    ),
                ]
            )
            return str(response.content)
        except Exception as exc:
            logger.exception("Groq Enter Pro prompt generation failed")
            raise GroqIntegrationError(f"Groq prompt generation failed: {exc}") from exc
