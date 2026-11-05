"""Regenerate the multi-resolution Windows icon (Pillow, build-time only)."""
from pathlib import Path
from PIL import Image, ImageDraw
im=Image.new("RGBA",(512,512))
d=ImageDraw.Draw(im)
d.rounded_rectangle((14,14,498,498),radius=118,fill="#192941")
# A mint speech bubble with a cut-out waveform; legible even at 16 px.
d.rounded_rectangle((84,100,428,365),radius=78,fill="#65edd0")
d.polygon([(134,337),(134,414),(228,337)],fill="#65edd0")
for x,h in [(158,45),(207,99),(256,153),(305,99),(354,45)]:
    d.rounded_rectangle((x-11,231-h//2,x+11,231+h//2),radius=11,fill="#192941")
im.save(Path(__file__).with_name('protocol.ico'),sizes=[(x,x) for x in (16,20,24,32,40,48,64,128,256)])
