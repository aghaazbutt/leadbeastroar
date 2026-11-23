"""WeasyPrint ReportRenderer.

Renders a Jinja2 template to HTML and then to PDF. Used for Visibility
Reports (the one-pager delivered to prospects).
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from leadbeast.adapters.protocols import ReportRenderer


class WeasyReportRenderer(ReportRenderer):
    key = "weasy"

    def __init__(self, template_dir: str | Path) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )

    async def render_pdf(self, *, template: str, context: dict[str, object]) -> bytes:
        try:
            from weasyprint import HTML  # local import; heavy
        except ImportError as exc:
            raise RuntimeError(
                "weasyprint not installed. Add to pyproject or install system libs."
            ) from exc

        html_doc = self._env.get_template(template).render(**context)
        return HTML(string=html_doc).write_pdf()  # type: ignore[no-any-return]
