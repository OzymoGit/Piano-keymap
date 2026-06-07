import pathlib

p = pathlib.Path("ui/midiPlayer.py")
text = p.read_text(encoding="utf-8")
# Replace the class variable reference too (MidiPlayerTab.midiFrame if it exists)
text = text.replace("self.midiFrame", "self.midiScrollFrame")
p.write_text(text, encoding="utf-8")
