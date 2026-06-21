from __future__ import annotations

import logging
import json
from typing import Any

from langchain_groq import ChatGroq

from app.models.incident import IncidentAnalysis, ParcleDocument, RequestClassification
from app.models.produck import NormalizedProduckRequest, ProduckTicket
from app.integrations.produck.ticket_mapper import compact_ticket_evidence
from app.prompts.incident import (
    ANALYSIS_SYSTEM_PROMPT,
    ENTERPRO_SYSTEM_PROMPT,
    PRODUCK_NORMALIZATION_SYSTEM_PROMPT,
    PRODUCK_TOOL_SELECTION_SYSTEM_PROMPT,
    REQUEST_CLASSIFICATION_SYSTEM_PROMPT,
)

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

    @staticmethod
    def _context(documents: list[ParcleDocument], empty_message: str) -> str:
        return "\n\n".join(
            f"[{doc.title}] ({doc.reference or 'no reference'})\n{doc.content}" for doc in documents
        ) or empty_message

    def classify_request(self, request: str, documents: list[ParcleDocument]) -> RequestClassification:
        context = self._context(
            documents,
            "No documentation was returned by Parcle. Classify conservatively from the user request.",
        )
        try:
            structured_llm = self._llm().with_structured_output(RequestClassification)
            return structured_llm.invoke(
                [
                    ("system", REQUEST_CLASSIFICATION_SYSTEM_PROMPT),
                    ("human", f"User request:\n{request}\n\nParcle memory:\n{context}"),
                ]
            )
        except Exception as exc:
            logger.exception("Groq request classification failed")
            raise GroqIntegrationError(f"Groq request classification failed: {exc}") from exc

    def analyze(self, incident: str, documents: list[ParcleDocument]) -> IncidentAnalysis:
        context = self._context(
            documents,
            "No documentation was returned by Parcle. Clearly account for this uncertainty.",
        )
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
        context = self._context(documents, "No Parcle memory answer was returned.")
        try:
            response = self._llm().invoke(
                [
                    ("system", ENTERPRO_SYSTEM_PROMPT),
                    (
                        "human",
                        f"Incident: {incident}\nAnalysis: {analysis.model_dump_json(indent=2)}\n"
                        f"Documentation references: {references}\nDocumentation evidence:\n{context}",
                    ),
                ]
            )
            return str(response.content)
        except Exception as exc:
            logger.exception("Groq Enter Pro prompt generation failed")
            raise GroqIntegrationError(f"Groq prompt generation failed: {exc}") from exc

    def normalize_produck_ticket(self, ticket: ProduckTicket) -> NormalizedProduckRequest:
        evidence = compact_ticket_evidence(ticket)
        try:
            structured_llm = self._llm().with_structured_output(NormalizedProduckRequest)
            return structured_llm.invoke(
                [
                    ("system", PRODUCK_NORMALIZATION_SYSTEM_PROMPT),
                    (
                        "human",
                        "Compact Produck evidence. Use only this packet; do not assume hidden DOM details.\n"
                        f"{json.dumps(evidence, indent=2, ensure_ascii=True)}",
                    ),
                ]
            )
        except Exception as exc:
            logger.exception("Groq Produck normalization failed")
            raise GroqIntegrationError(f"Groq Produck normalization failed: {exc}") from exc

    def choose_produck_tool(self, tools: list[dict[str, Any]], purpose: str) -> str:
        try:
            response = self._llm().invoke(
                [
                    ("system", PRODUCK_TOOL_SELECTION_SYSTEM_PROMPT),
                    (
                        "human",
                        f"Purpose: {purpose}\n\nAvailable tools:\n{tools}",
                    ),
                ]
            )
            return str(response.content).strip().strip('"')
        except Exception:
            logger.exception("Groq Produck tool selection failed")
            return ""
