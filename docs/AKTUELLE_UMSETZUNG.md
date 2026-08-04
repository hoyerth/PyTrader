# AKTUELLE UMSETZUNG – Phase 15: Service UI und Analytics

## 15.01  Symbol-Auswahl und Favoriten

- generische Umsetzung, wird dann in den Fenstern Service und Analytics genutzt
- erstellung einer funktion get_symbols, die alle verfügbaren Symbole meines Brokers über MT5 bezieht und in eine persistente liste in app_data schreibt
- DropDown zeigt nur die als Favoriten deklarierten Symbole
- ein kleiner button mit nur einem * als icon rechts daneben öffnet ein auswahl fenster symbols_win
- symbols_win: 
  - nicht modal, liest beim öffnen get_symbols, wenn nicht möglich, error in log und anzeige der vorhandenen liste aus app_data
  - Suchfeld oben, darunter eine listbox mit allen Symbolen
  - Suchfeld findet den ersten passenden eintrag in der listbox und setzt den cursor darauf, der treffer soll sichtbar in der listbox sein
  - listbox hat eine zweite spalte als favoritenanzeige: * wenn favorit, leer wenn kein favorit
  - in der listbox schaltet ein mausklick in die favoriten spalte das symbol als favorit ein oder aus
  - das fenster schliessen über 1. Button schliessen 2. Windows X 3. ESC
- Einbau der Symbollogik in service_win und analytics_win

