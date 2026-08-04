# test/check_p15_s1_symbols.py
"""
Phase 15 15.01 – Headless Validierung (KEINE UI, KEIN QApplication.exec()).

Prueft das Symbol- & Favoriten-System rein auf Logik-/DB-Ebene:

A) DB-Persistenz & Defaults:
   - broker_symbols-Tabelle wird angelegt (idempotent).
   - Standard-Defaults SILVER/GOLD/BTCUSD sind als Favoriten vorhanden.
   - ensure_defaults() ist idempotent (Favoriten-Flags bleiben erhalten).

B) Lese-API:
   - get_symbols() liefert alle Symbole inkl. path/is_favorite.
   - get_favorite_symbols() liefert nur Favoriten (sortiert).
   - get_symbol() liefert ein einzelnes Symbol (case-insensitive).

C) Favoriten-Toggle:
   - toggle_favorite() kippt den Zustand und liefert den NEUEN Zustand.
   - Unbekanntes Symbol wird beim Toggle als Favorit angelegt.

D) Broker-Upsert:
   - upsert_from_broker() fuegt neue Symbole hinzu (path/updated_at).
   - Bestehende Favoriten-Flags bleiben beim Upsert unangetastet.

E) MT5-Fallback (sync_from_broker / sync_from_broker_with_status):
   - MT5 nicht verfuegbar (initialize()==False) -> Fallback auf DB-Tabelle.
   - MT5 verfuegbar (symbols_get()) -> Upsert + Rueckgabe der DB-Liste.
   - MT5 wirft Exception -> Fallback auf DB-Tabelle.
   - sync_from_broker_with_status() liefert Status "live"/"fallback" und eine
     Fehlermeldung (User-Anweisung: Fehlermeldung im Log statt stillem Fallback).

F) EventBus:
   - favorites_changed wird nach Toggle emittiert (Verbindung wird aufgerufen).
   - profile_changed/service_set_changed existieren (Signal-API).

Test-DB liegt im Unterordner test/ (Regel: keine Test-DBs im Root/data).
"""
import os
import sys

sys.path.insert(0, r"F:\Python\PyTrader")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "p15_s1_symbols_test.duckdb")
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

from symbol_repository import SymbolRepository, DEFAULT_SYMBOLS  # noqa: E402
from db_service import DbPool  # noqa: E402

FAILURES: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


repo = SymbolRepository(db_path=TEST_DB)

# ---------------------------------------------------------------------------
# A) DB-Persistenz & Defaults
# ---------------------------------------------------------------------------
con = DbPool.get(TEST_DB)
tables = [r[0] for r in con.execute(
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_name = 'broker_symbols'").fetchall()]
check("A1) broker_symbols-Tabelle angelegt", "broker_symbols" in tables)

defaults = [s.get("symbol") for s in repo.get_symbols()]
check("A2) Defaults vorhanden (SILVER/GOLD/BTCUSD)",
      defaults == ["BTCUSD", "GOLD", "SILVER"], str(defaults))

favs = repo.get_favorite_symbols()
check("A3) Defaults sind Favoriten",
      set(favs) == {"SILVER", "GOLD", "BTCUSD"}, str(favs))

# Idempotenz: ensure_defaults() darf bestehende Favoriten-Flags nicht aendern
repo.toggle_favorite("GOLD")          # GOLD jetzt KEIN Favorit mehr
repo.ensure_defaults()                # darf GOLD nicht zuruecksetzen
check("A4) ensure_defaults() idempotent (GOLD bleibt Nicht-Favorit)",
      "GOLD" not in repo.get_favorite_symbols(),
      str(repo.get_favorite_symbols()))
repo.toggle_favorite("GOLD")          # zuruecksetzen fuer spaetere Checks

# ---------------------------------------------------------------------------
# B) Lese-API
# ---------------------------------------------------------------------------
syms = repo.get_symbols()
check("B1) get_symbols() liefert Dicts mit symbol/path/is_favorite",
      all(k in syms[0] for k in ("symbol", "path", "is_favorite", "updated_at")),
      str(syms[0].keys()))

g = repo.get_symbol("silver")         # case-insensitive
check("B2) get_symbol() case-insensitive",
      g is not None and g["symbol"] == "SILVER")

check("B3) get_symbol() unbekannt -> None",
      repo.get_symbol("UNBEKANNT") is None)

# ---------------------------------------------------------------------------
# C) Favoriten-Toggle
# ---------------------------------------------------------------------------
new_state = repo.toggle_favorite("SILVER")
check("C1) toggle liefert NEUEN Zustand (SILVER -> False)", new_state is False)
check("C2) SILVER aus Favoriten entfernt",
      "SILVER" not in repo.get_favorite_symbols())

new_state = repo.toggle_favorite("SILVER")
check("C3) erneuter Toggle (SILVER -> True)", new_state is True)
check("C4) SILVER wieder Favorit", "SILVER" in repo.get_favorite_symbols())

repo.toggle_favorite("EURUSD")        # unbekannt -> wird als Favorit angelegt
check("C5) unbekanntes Symbol wird als Favorit angelegt",
      repo.get_symbol("EURUSD") is not None
      and repo.get_symbol("EURUSD")["is_favorite"] is True)

# ---------------------------------------------------------------------------
# D) Broker-Upsert
# ---------------------------------------------------------------------------
n = repo.upsert_from_broker([("GBPUSD", "Forex\\GBPUSD"),
                             ("EURUSD", "Forex\\EURUSD"),
                             ("XAUUSD", "Metals\\XAUUSD")])
check("D1) upsert_from_broker verarbeitet 3 Symbole", n == 3, str(n))
check("D2) GBPUSD/XAUUSD angelegt",
      repo.get_symbol("GBPUSD") is not None and repo.get_symbol("XAUUSD") is not None)
check("D3) path gespeichert (EURUSD -> Forex\\EURUSD)",
      repo.get_symbol("EURUSD")["path"] == "Forex\\EURUSD")
check("D4) Favoriten-Flag beim Upsert unangetastet (EURUSD bleibt Favorit)",
      repo.get_symbol("EURUSD")["is_favorite"] is True)
check("D5) Duplikate: gleicher Symbol-Name nur 1 Zeile",
      sum(1 for s in repo.get_symbols() if s["symbol"] == "EURUSD") == 1)

# ---------------------------------------------------------------------------
# E) MT5-Fallback (sync_from_broker)
# ---------------------------------------------------------------------------
_original_mt5 = sys.modules.get("MetaTrader5")


class _FakeSymbol:
    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path


class _FakeMT5_Offline:
    def initialize(self):
        return False

    def symbols_get(self):
        raise AssertionError("symbols_get() darf bei initialize()==False nicht gerufen werden")


class _FakeMT5_Online:
    def initialize(self):
        return True

    def symbols_get(self):
        return [_FakeSymbol("AUDUSD", "Forex\\AUDUSD"),
                _FakeSymbol("NZDUSD", "Forex\\NZDUSD")]


class _FakeMT5_Error:
    def initialize(self):
        raise RuntimeError("MT5-DLL nicht ladbar")


try:
    # E1) MT5 offline -> Fallback auf DB (unveraendert)
    sys.modules["MetaTrader5"] = _FakeMT5_Offline()
    before = repo.count()
    result = repo.sync_from_broker()
    check("E1) MT5 offline -> Fallback auf DB-Tabelle",
          repo.count() == before and isinstance(result, list)
          and len(result) == before, f"count={repo.count()}")

    # E1b) sync_from_broker_with_status: Status 'fallback' + Fehlermeldung
    symbols, status, error = repo.sync_from_broker_with_status()
    check("E1b) Status 'fallback' + Fehlermeldung bei MT5 offline",
          status == "fallback" and bool(error)
          and "initialize" in error.lower(),
          f"status={status} error={error}")

    # E2) MT5 online -> Upsert + Rueckgabe der DB-Liste
    sys.modules["MetaTrader5"] = _FakeMT5_Online()
    result = repo.sync_from_broker()
    check("E2) MT5 online -> AUDUSD/NZDUSD uebernommen",
          repo.get_symbol("AUDUSD") is not None
          and repo.get_symbol("NZDUSD") is not None)
    check("E3) Rueckgabe ist die DB-Liste (alle Symbole)",
          isinstance(result, list) and repo.count() == len(result))

    # E3b) Upsert setzt neue Symbole NICHT automatisch auf Favorit
    check("E3b) neue MT5-Symbole sind keine Favoriten (außer Defaults)",
          repo.get_symbol("AUDUSD")["is_favorite"] is False
          and repo.get_symbol("SILVER")["is_favorite"] is True)

    # E3c) sync_from_broker_with_status: Status 'live' ohne Fehlermeldung
    symbols, status, error = repo.sync_from_broker_with_status()
    check("E3c) Status 'live' ohne Fehlermeldung bei MT5 online",
          status == "live" and error is None
          and len(symbols) == repo.count(),
          f"status={status} error={error}")

    # E4) MT5 wirft Exception -> Fallback auf DB
    sys.modules["MetaTrader5"] = _FakeMT5_Error()
    before = repo.count()
    result = repo.sync_from_broker()
    check("E4) MT5-Exception -> Fallback auf DB-Tabelle",
          repo.count() == before and len(result) == before, f"count={repo.count()}")

    # E4b) sync_from_broker_with_status: Status 'fallback' + Meldung bei Exception
    symbols, status, error = repo.sync_from_broker_with_status()
    check("E4b) Status 'fallback' + Fehlermeldung bei MT5-Exception",
          status == "fallback" and bool(error), f"status={status} error={error}")

    # E5) MT5-Import schlaegt fehl (sys.modules=None) -> Fallback + Meldung
    sys.modules["MetaTrader5"] = None
    symbols, status, error = repo.sync_from_broker_with_status()
    check("E5) MT5-Import-Fehler -> Fallback + Meldung",
          status == "fallback" and bool(error)
          and len(symbols) == repo.count(),
          f"status={status} error={error}")
finally:
    if _original_mt5 is None:
        sys.modules.pop("MetaTrader5", None)
    else:
        sys.modules["MetaTrader5"] = _original_mt5

# ---------------------------------------------------------------------------
# F) EventBus
# ---------------------------------------------------------------------------
from config.event_bus import event_bus  # noqa: E402

calls = []
event_bus.favorites_changed.connect(lambda: calls.append("favorites"))
event_bus.favorites_changed.emit()
check("F1) favorites_changed wird emittiert", calls == ["favorites"], str(calls))

profile_calls = []
event_bus.profile_changed.connect(profile_calls.append)
event_bus.profile_changed.emit("profil_alpha")
check("F2) profile_changed mit Payload", profile_calls == ["profil_alpha"], str(profile_calls))

set_calls = []
event_bus.service_set_changed.connect(lambda: set_calls.append(1))
event_bus.service_set_changed.emit()
check("F3) service_set_changed wird emittiert", set_calls == [1], str(set_calls))

# ---------------------------------------------------------------------------
# Aufraeumen
# ---------------------------------------------------------------------------
try:
    os.remove(TEST_DB)
except OSError:
    pass

print("-" * 60)
if FAILURES:
    print(f"FEHLER: {len(FAILURES)} Pruefung(en) fehlgeschlagen: {FAILURES}")
    sys.exit(1)
print("ALLE PRUEFUNGEN BESTANDEN (OK)")
sys.exit(0)
