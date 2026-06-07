import pathlib

p = pathlib.Path("ui/midiPlayer.py")
text = p.read_text(encoding="utf-8")
# Replace all references from self.midiFrame to self.midiScrollFrame
new_text = text.replace("self.midiFrame", "self.midiScrollFrame")
if new_text == text:
    print("No replacements made!")
else:
    count = len(new_text.split("self.midiScrollFrame")) - len(
        text.split("self.midiScrollFrame")
    )
    print(f"Replaced {count} occurrences")
    p.write_text(new_text, encoding="utf-8")
