"""
ProffAgenten CLI – command-line interface.

Usage examples:
  proff create                # registrer/oppdater agenten i Foundry
  proff chat                  # interaktiv chat
  proff create chat           # registrer og start chat i én operasjon
  proff info                  # vis konfigurasjon

Forutsetninger:
  - Kopier .env.example til .env og fyll inn PROJECT_ENDPOINT
  - Logg inn med: azd auth login --scope https://ai.azure.com/.default
"""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from .agent import ProffAgent
from .config import settings

app = typer.Typer(
    name="proff",
    help="ProffAgenten – Bedriftsinformasjon fra norske registre",
    no_args_is_help=True,
)
console = Console()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )


@app.command()
def create(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Registrer / oppdater ProffAgenten i Azure AI Foundry."""
    _setup_logging("DEBUG" if verbose else settings.log_level)
    agent = ProffAgent()
    with console.status("Oppretter agent i Foundry…"):
        agent.create_or_update_agent()


@app.command()
def chat(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Vis debug-logger"),
) -> None:
    """Start en interaktiv chat med ProffAgenten."""
    _setup_logging("DEBUG" if verbose else settings.log_level)

    console.print(
        Panel.fit(
            "[bold cyan]ProffAgenten – Bedriftsinformasjon[/bold cyan]\n"
            "Skriv spørsmålet ditt og trykk Enter. Skriv [bold]avslutt[/bold] for å avslutte.\n\n"
            "[dim]Eksempler: 'Finn info om Equinor', 'Søk etter IT-selskaper i Oslo'[/dim]",
            title="🏢 ProffAgenten",
        )
    )

    agent = ProffAgent()

    while True:
        try:
            question = Prompt.ask("[bold cyan]Du[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Avslutter.[/dim]")
            break

        if question.strip().lower() in {"avslutt", "exit", "quit", "bye"}:
            console.print("[dim]Ha det bra![/dim]")
            break

        if not question.strip():
            continue

        with console.status("ProffAgenten søker…"):
            try:
                answer = agent.ask(question)
            except Exception as exc:
                console.print(f"[red]Feil: {exc}[/red]")
                continue

        console.print(Panel(Markdown(answer), title="[bold green]ProffAgenten[/bold green]", border_style="green"))


@app.command()
def info() -> None:
    """Vis gjeldende konfigurasjon."""
    _setup_logging(settings.log_level)
    console.print("[bold]ProffAgenten konfigurasjon[/bold]")
    console.print(f"  Backend        : Azure AI Foundry")
    console.print(f"  Endepunkt      : {settings.project_endpoint or '[red]ikke satt[/red]'}")
    console.print(f"  Modell         : {settings.model_deployment_name}")
    console.print(f"  Agentnavn      : {settings.agent_name}")


if __name__ == "__main__":
    app()
