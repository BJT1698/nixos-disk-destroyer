"""MVS Disk Destroyer - interfaccia testuale (Textual) per la cancellazione sicura dei dischi.

Schermate: Dischi -> Metodo -> Conferma -> Avanzamento/Riepilogo.
Gira sulla console Linux (solo tastiera); start.sh imposta la palette dei 16 colori sul tema scuro.
"""
from __future__ import annotations

import os
import subprocess
import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (Button, Checkbox, DataTable, Footer, Input, Label, RadioButton,
                             RadioSet, Static)

import disks as dk
import wipe as wp

TITLE = "MVS Disk Destroyer"

# La console Linux ha un font da 512 glifi: solo ASCII, linee semplici/doppie e blocchi (CP437).
for _cls, _inner in ((RadioButton, "*"), (Checkbox, "X")):
    _cls.BUTTON_LEFT, _cls.BUTTON_INNER, _cls.BUTTON_RIGHT = ("(", _inner, ")") if _cls is RadioButton else ("[", _inner, "]")


def bar(fraction: float | None, width: int, ok: bool = False, spin: int = 0) -> str:
    """Barra di avanzamento con blocchi pieni/ombreggiati; indeterminata se fraction e' None."""
    if fraction is None:
        pos = spin % (width - 6)
        return "[dim]" + "\u2591" * pos + "[/][b blue]" + "\u2588" * 6 + "[/][dim]" + "\u2591" * (width - 6 - pos) + "[/]"
    full = int(round(fraction * width))
    color = "green" if ok else "blue"
    return f"[b {color}]" + "\u2588" * full + "[/][dim]" + "\u2591" * (width - full) + "[/]"
CONFIRM_WORD = "CANCELLA"


class Banner(Static):
    """Intestazione con titolo e passo corrente."""

    def __init__(self, step: str) -> None:
        super().__init__(f"[b]{TITLE}[/b]   [dim]·[/dim]   {step}", id="banner")


# --------------------------------------------------------------------------------------------
class DiskScreen(Screen):
    BINDINGS = [
        Binding("space", "toggle", "Seleziona", key_display="Spazio"),
        Binding("a", "toggle_all", "Tutti"),
        Binding("r", "rescan", "Aggiorna"),
        Binding("enter", "next", "Avanti", priority=True, key_display="Invio"),
        Binding("q", "app.quit_menu", "Esci"),
    ]

    def compose(self) -> ComposeResult:
        yield Banner("1/3  Scegli i dischi da cancellare")
        yield DataTable(id="disks", cursor_type="row", zebra_stripes=True)
        yield Static(id="hint")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_columns("", "Disco", "Tipo", "Modello", "Seriale", "Dimensione", "Canc. hardware", "Stato")
        self.action_rescan()

    def action_rescan(self) -> None:
        app: DestroyerApp = self.app      # type: ignore[assignment]
        app.disks = dk.scan()
        app.selected &= {d.name for d in app.disks if not d.mounted}
        self.refresh_table()

    def refresh_table(self) -> None:
        app: DestroyerApp = self.app      # type: ignore[assignment]
        t = self.query_one(DataTable)
        row = t.cursor_row
        t.clear()
        for d in app.disks:
            mark = "[b red]\\[X][/]" if d.name in app.selected else "[dim]\\[ ][/]"
            state = f"[yellow]montato[/]" if d.mounted else "[green]libero[/]"
            t.add_row(mark, f"[b]{d.path}[/]", d.kind, d.model or "-", d.serial or "-", d.size_text,
                      d.hw_text, state, key=d.name)
        if app.disks:
            t.move_cursor(row=min(row, len(app.disks) - 1))
        n = len(app.selected)
        size = sum(d.size for d in app.disks if d.name in app.selected)
        hint = (f"[b red]{n} disco/i selezionati[/] ({dk.human_size(size)})   " if n else
                "[dim]Nessun disco selezionato[/]   ")
        hint += "[dim]Spazio = seleziona · A = tutti · Invio = avanti · R = aggiorna[/]"
        if not app.disks:
            hint = "[yellow]Nessun disco trovato. Premi R per riprovare.[/]"
        self.query_one("#hint", Static).update(hint)

    def _current(self) -> dk.Disk | None:
        app: DestroyerApp = self.app      # type: ignore[assignment]
        t = self.query_one(DataTable)
        if not app.disks or t.cursor_row < 0:
            return None
        return app.disks[t.cursor_row]

    def action_toggle(self) -> None:
        app: DestroyerApp = self.app      # type: ignore[assignment]
        d = self._current()
        if not d:
            return
        if d.mounted:
            self.notify(f"{d.path} e' montato: non si puo' cancellare.", severity="warning")
            return
        app.selected ^= {d.name}
        self.refresh_table()

    def action_toggle_all(self) -> None:
        app: DestroyerApp = self.app      # type: ignore[assignment]
        free = {d.name for d in app.disks if not d.mounted}
        app.selected = set() if app.selected == free else free
        self.refresh_table()

    def action_next(self) -> None:
        app: DestroyerApp = self.app      # type: ignore[assignment]
        if not app.selected:
            self.notify("Seleziona almeno un disco con la barra spaziatrice.", severity="warning")
            return
        app.push_screen(MethodScreen())


# --------------------------------------------------------------------------------------------
class MethodScreen(Screen):
    BINDINGS = [
        Binding("enter", "next", "Avanti", priority=True, key_display="Invio"),
        Binding("escape", "back", "Indietro", key_display="Esc"),
    ]

    def compose(self) -> ComposeResult:
        app: DestroyerApp = self.app      # type: ignore[assignment]
        yield Banner("2/3  Scegli il metodo di cancellazione")
        with Horizontal(id="method-row"):
            with RadioSet(id="methods"):
                for i, m in enumerate(wp.METHODS):
                    yield RadioButton(m.title, value=(m.key == app.method.key), id=f"m-{m.key}")
            yield Static(id="method-info")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(RadioSet).focus()
        self.show_info()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        app: DestroyerApp = self.app      # type: ignore[assignment]
        app.method = wp.METHODS[event.index]
        self.show_info()

    def show_info(self) -> None:
        app: DestroyerApp = self.app      # type: ignore[assignment]
        m = app.method
        lines = [f"[b]{m.title}[/b]", "", m.detail, "", "[b]Cosa succede ai dischi selezionati:[/b]"]
        for d in app.selected_disks():
            lines.append(f"  [b]{d.path}[/] {d.kind} {d.size_text}: {plan_for(d, m)}")
        self.query_one("#method-info", Static).update("\n".join(lines))

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_next(self) -> None:
        app: DestroyerApp = self.app      # type: ignore[assignment]
        if app.method.hardware:
            missing = [d.path for d in app.selected_disks() if not d.hw_methods]
            if missing:
                self.notify("Cancellazione hardware non disponibile su: " + ", ".join(missing),
                            severity="error")
                return
        app.push_screen(ConfirmScreen())


def plan_for(d: dk.Disk, m: wp.Method) -> str:
    if m.key == "auto":
        hw = d.hw_methods
        return f"[green]hardware: {hw[0]}[/]" if hw else "1 passaggio casuale"
    if m.hardware:
        return f"[green]{d.hw_methods[0]}[/]" if d.hw_methods else "[red]non supportato[/]"
    if m.key == "quick":
        return "firme e partizioni" + (" + TRIM" if d.discard else "")
    return f"{len(m.passes)} passaggio/i: " + ", ".join(wp.PATTERN_NAME[p] for p in m.passes)


# --------------------------------------------------------------------------------------------
class ConfirmScreen(Screen):
    BINDINGS = [Binding("escape", "back", "Indietro", key_display="Esc")]

    def compose(self) -> ComposeResult:
        app: DestroyerApp = self.app      # type: ignore[assignment]
        yield Banner("3/3  Conferma")
        with Vertical(id="confirm-box"):
            yield Static("[b]ATTENZIONE: tutti i dati sui dischi seguenti verranno distrutti "
                         "in modo definitivo.[/b]", id="warn")
            rows = [f"  [b]{d.path}[/]  {d.kind}  {d.model or '-'}  S/N {d.serial or '-'}  "
                    f"[b]{d.size_text}[/]" for d in app.selected_disks()]
            yield Static("\n".join(rows), id="confirm-disks")
            yield Static(f"Metodo: [b]{app.method.title}[/b]", id="confirm-method")
            yield Label(f"Per procedere scrivi [b]{CONFIRM_WORD}[/b] e premi Invio:")
            yield Input(placeholder=CONFIRM_WORD, id="confirm-input")
            yield Checkbox("Spegni il PC al termine", value=app.poweroff, id="poweroff")
            with Horizontal(id="confirm-buttons"):
                yield Button("Indietro", id="back")
                yield Button("Avvia cancellazione", id="go", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self.app.poweroff = event.value      # type: ignore[attr-defined]

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.try_start()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.action_back()
        else:
            self.try_start()

    def try_start(self) -> None:
        if self.query_one(Input).value.strip() != CONFIRM_WORD:
            self.notify(f"Scrivi esattamente {CONFIRM_WORD} (maiuscolo) per confermare.", severity="error")
            return
        self.app.switch_screen(RunScreen())

    def action_back(self) -> None:
        self.app.pop_screen()


# --------------------------------------------------------------------------------------------
class DiskRow(Horizontal):
    def __init__(self, job: wp.Job) -> None:
        super().__init__(classes="job")
        self.job = job

    def compose(self) -> ComposeResult:
        d = self.job.disk
        yield Static(f"[b]{d.path}[/]\n[dim]{d.kind} {d.size_text}[/]", classes="job-name")
        with Vertical(classes="job-main"):
            yield Static("", classes="job-step")
            yield Static("", classes="job-bar")
        yield Static("", classes="job-stats")

    def refresh_job(self) -> None:
        with self.job.lock:
            p = wp.Progress(**{k: getattr(self.job.p, k) for k in ("step", "fraction", "speed", "eta",
                                                                  "done", "ok", "error")})
        step = self.query_one(".job-step", Static)
        barw = self.query_one(".job-bar", Static)
        stats = self.query_one(".job-stats", Static)
        width = max(10, barw.size.width - 6)
        self.spin = getattr(self, "spin", 0) + 1
        if p.done and p.ok:
            step.update("[b green]OK - completato[/]")
            barw.update(bar(1.0, width, ok=True) + " 100%")
            self.add_class("ok")
        elif p.done:
            step.update(f"[b red]ERRORE: {p.error}[/]")
            self.add_class("err")
        else:
            step.update(p.step)
            pct = "" if p.fraction is None else f" {p.fraction * 100:3.0f}%"
            barw.update(bar(p.fraction, width, spin=self.spin) + pct)
        el = (self.job.ended or time.time()) - self.job.started
        stats.update(f"{wp.fmt_speed(p.speed)}  [dim]trascorso[/] {wp.fmt_time(el)}\n"
                     + ("" if p.done else f"[dim]residuo[/] {wp.fmt_time(p.eta)}"))


class RunScreen(Screen):
    BINDINGS = [
        Binding("p", "poweroff", "Spegni", show=False),
        Binding("r", "reboot", "Riavvia", show=False),
        Binding("n", "again", "Nuova cancellazione", show=False),
    ]

    def compose(self) -> ComposeResult:
        app: DestroyerApp = self.app      # type: ignore[assignment]
        self.jobs = [wp.Job(d, app.method) for d in app.selected_disks()]
        yield Banner(f"Cancellazione in corso  ·  {app.method.title}")
        with VerticalScroll(id="jobs"):
            for j in self.jobs:
                yield DiskRow(j)
        yield Static(id="log")
        yield Static(id="summary")
        with Horizontal(id="end-buttons"):
            yield Button("Spegni  [P]", id="off", variant="error")
            yield Button("Riavvia  [R]", id="reboot")
            yield Button("Nuova cancellazione  [N]", id="again", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#end-buttons").display = False
        self.finished = False
        self.countdown: int | None = None
        for j in self.jobs:
            j.start()
        self.set_interval(0.5, self.tick)

    def tick(self) -> None:
        for row in self.query(DiskRow):
            row.refresh_job()
        lines = []
        for j in self.jobs:
            with j.lock:
                lines += j.p.log[-3:]
        self.query_one("#log", Static).update("[dim]" + "\n".join(lines[-6:]).replace("[", "\\[") + "[/]")
        if not self.finished and all(j.p.done for j in self.jobs):
            self.finish()
        if self.countdown is not None:
            self.countdown -= 1
            if self.countdown <= 0:
                self.action_poweroff()
            else:
                self.query_one("#summary", Static).update(self.summary_text()
                                                          + f"\n[yellow]Spegnimento tra {self.countdown // 2} s"
                                                          " - premi un tasto qualsiasi per annullare[/]")

    def summary_text(self) -> str:
        ok = sum(1 for j in self.jobs if j.p.ok)
        ko = len(self.jobs) - ok
        if ko == 0:
            return f"[b green]Tutti i {ok} dischi sono stati cancellati.[/]"
        return f"[b red]{ko} disco/i con errori[/], [green]{ok} completato/i[/]. Vedi i dettagli sopra."

    def finish(self) -> None:
        self.finished = True
        self.query_one("#summary", Static).update(self.summary_text())
        self.query_one("#end-buttons").display = True
        self.query_one("#again", Button).focus()
        os.system("printf '\\a' > /dev/tty1 2>/dev/null")
        all_ok = all(j.p.ok for j in self.jobs)
        if self.app.poweroff and all_ok:      # type: ignore[attr-defined]
            self.countdown = 60               # tick ogni 0,5 s -> 30 s

    def on_key(self, event) -> None:
        if self.countdown is not None:
            self.countdown = None
            self.query_one("#summary", Static).update(self.summary_text() + "\n[dim]Spegnimento annullato.[/]")
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        {"off": self.action_poweroff, "reboot": self.action_reboot, "again": self.action_again}[event.button.id]()

    def action_poweroff(self) -> None:
        if self.finished:
            subprocess.run(["systemctl", "poweroff"])

    def action_reboot(self) -> None:
        if self.finished:
            subprocess.run(["systemctl", "reboot"])

    def action_again(self) -> None:
        if self.finished:
            app: DestroyerApp = self.app      # type: ignore[assignment]
            app.selected = set()
            app.switch_screen(DiskScreen())


# --------------------------------------------------------------------------------------------
class DestroyerApp(App):
    CSS_PATH = "app.tcss"
    ENABLE_COMMAND_PALETTE = False
    TITLE = TITLE
    BINDINGS = [Binding("ctrl+c", "quit_menu", "Esci", show=False)]

    def __init__(self) -> None:
        super().__init__()
        self.disks: list[dk.Disk] = []
        self.selected: set[str] = set()
        self.method: wp.Method = wp.METHODS[0]
        self.poweroff = True

    def selected_disks(self) -> list[dk.Disk]:
        return [d for d in self.disks if d.name in self.selected]

    def on_mount(self) -> None:
        # colori ANSI: la palette della console (start.sh) li mappa sul tema scuro MVS
        for name in ("ansi-dark", "textual-ansi"):      # il nome dipende dalla versione di Textual
            if name in self.available_themes:
                self.theme = name
                break
        self.push_screen(DiskScreen())

    def action_quit_menu(self) -> None:
        if isinstance(self.screen, RunScreen) and not self.screen.finished:
            self.notify("Cancellazione in corso: attendi la fine.", severity="warning")
            return
        self.exit()


if __name__ == "__main__":
    if os.geteuid() != 0:
        raise SystemExit("Serve root: sudo python3 app.py")
    DestroyerApp().run()
