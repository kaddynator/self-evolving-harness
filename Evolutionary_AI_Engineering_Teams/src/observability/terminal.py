from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from rich.table import Table

from src.observability.events import E, PipelineEvent

_c = Console(highlight=False)


def _ts(event: PipelineEvent) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(event.timestamp).strftime("%H:%M:%S")


class RichTerminalObserver:
    """Subscribes to EventBus and renders live colored output via rich."""

    def on_event(self, event: PipelineEvent) -> None:
        t = event.type
        d = event.data
        ts = _ts(event)
        gen = event.generation

        if t == E.EVOLUTION_START:
            _c.print()
            _c.print(Panel(
                f"[bold cyan]{d.get('harness_id', '')}[/]\n"
                f"[dim]{d.get('objective', '')[:80]}[/]\n"
                f"Max generations: [bold]{d.get('max_generations', 1)}[/]",
                title="[bold magenta]🧬 HARNESS EVOLUTION[/]",
                border_style="magenta",
                expand=False,
            ))

        elif t == E.GENERATION_START:
            _c.print()
            _c.print(Rule(
                f"[bold yellow]Generation {gen}[/]",
                style="yellow",
                align="left",
            ))

        elif t == E.PHASE_START:
            phase = d.get("phase", "")
            agents = ", ".join(d.get("agents", []))
            _c.print(f"  [dim]{ts}[/]  [bold]▶ Phase:[/] [cyan]{phase}[/]  [dim]({agents})[/]")

        elif t == E.AGENT_START:
            aid = d.get("agent_id", "")
            name = d.get("agent_name", "")
            _c.print(f"    [dim]{ts}[/]  [yellow]⟳[/] [bold]{aid}[/]  [dim]{name}[/]")

        elif t == E.AGENT_TOOL_CALL:
            tool = d.get("tool", "")
            ok = d.get("success", True)
            icon = "[green]⚒[/]" if ok else "[red]✗[/]"
            _c.print(f"      [dim]{ts}[/]  {icon}  [dim]{tool}[/]")

        elif t == E.AGENT_FINISH:
            aid = d.get("agent_id", "")
            ok = d.get("success", False)
            arts = d.get("artifacts", [])
            elapsed = d.get("elapsed", 0.0)
            icon = "[green]✓[/]" if ok else "[red]✗[/]"
            art_str = "  →  " + ", ".join(arts) if arts else ""
            _c.print(
                f"    [dim]{ts}[/]  {icon} [bold]{aid}[/]"
                f"  [dim]{elapsed:.2f}s[/][green]{art_str}[/]"
            )

        elif t == E.RUN_COMPLETE:
            ok = d.get("success", False)
            calls = d.get("total_tool_calls", 0)
            elapsed = d.get("elapsed", 0.0)
            icon = "[green]✓[/]" if ok else "[red]✗[/]"
            _c.print(
                f"\n  [dim]{ts}[/]  {icon} Run complete  "
                f"tool_calls=[bold]{calls}[/]  elapsed=[bold]{elapsed:.2f}s[/]"
            )

        elif t == E.EVALUATION_COMPLETE:
            score = d.get("score", 0.0)
            passed = d.get("passed", False)
            threshold = d.get("threshold", 70.0)
            color = "green" if passed else "red"
            verdict = "PASSED" if passed else "FAILED"

            tbl = Table(show_header=True, header_style="dim", expand=False, border_style="dim")
            tbl.add_column("Metric", style="dim")
            tbl.add_column("Score", justify="right")
            for name, val in d.get("metrics", {}).items():
                tbl.add_row(name, f"{val:+.1f}")

            _c.print(
                f"\n  Score: [{color}][bold]{score:.1f}[/bold][/]  "
                f"/ {threshold}  [{color}][bold]{verdict}[/bold][/]"
            )
            _c.print(tbl)

        elif t == E.WEAKNESS_MINED:
            sigs = d.get("signatures", [])
            if sigs:
                _c.print(f"\n  [bold red]Failure Signatures ({len(sigs)}):[/]")
                for s in sigs:
                    mech = s.get("mechanism", "")
                    behav = s.get("agent_behavior", "")
                    _c.print(f"    [red]•[/] [bold]{mech}[/]  [dim]{behav}[/]")
            else:
                _c.print("\n  [green]No failure signatures — harness is healthy.[/]")

        elif t == E.MUTATION_PROPOSED:
            idx = d.get("index", 0)
            total = d.get("total", 0)
            mut_type = d.get("mutation_type", "")
            effect = d.get("effect", "")
            _c.print(
                f"\n  [dim]{ts}[/]  Proposal [{idx}/{total}]  "
                f"[cyan]{mut_type}[/]  [dim]→ {effect[:70]}[/]"
            )

        elif t == E.GATE_DECISION:
            mut_type = d.get("mutation_type", "")
            accepted = d.get("accepted", False)
            reason = d.get("reason", "")
            if accepted:
                _c.print(f"    [green bold][ACCEPTED][/] {mut_type}")
            else:
                _c.print(f"    [red][rejected][/]  {mut_type}  [dim]{reason}[/]")

        elif t == E.GENERATION_FINISH:
            score = d.get("score", 0.0)
            accepted = d.get("accepted_candidate")
            if accepted:
                _c.print(f"\n  [green bold]=> Accepted candidate:[/] {accepted}  score={score:.1f}")
            else:
                _c.print(f"\n  [dim]=> No accepted candidate this generation.[/]")

        elif t == E.EVOLUTION_COMPLETE:
            gens = d.get("generations", 0)
            i_score = d.get("initial_score", 0.0)
            f_score = d.get("final_score", 0.0)
            delta = f_score - i_score
            color = "green" if delta >= 0 else "red"
            _c.print()
            _c.print(Panel(
                f"Generations: [bold]{gens}[/]  "
                f"Score: [bold]{i_score:.1f}[/] → [{color}][bold]{f_score:.1f}[/][/]  "
                f"([{color}]{delta:+.1f}[/])",
                title="[bold magenta]🧬 Evolution Complete[/]",
                border_style="magenta",
                expand=False,
            ))
