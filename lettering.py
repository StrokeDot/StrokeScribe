"""Original single-line, slanted print alphabet; no font outlines or font dependency."""
from engine import Drawing, Stroke

# Coordinates on a 4 by 6 writing grid. Each | is a pen lift.
GLYPHS={
'A':'0,6 2,0 4,6|1,4 3,4','B':'0,6 0,0 3,0 4,1 3,3 0,3|3,3 4,4 4,5 3,6 0,6',
'C':'4,1 3,0 1,0 0,1 0,5 1,6 3,6 4,5','D':'0,6 0,0 2,0 4,2 4,4 2,6 0,6',
'E':'4,0 0,0 0,6 4,6|0,3 3,3','F':'0,6 0,0 4,0|0,3 3,3','G':'4,1 3,0 1,0 0,1 0,5 1,6 4,6 4,3 2,3',
'H':'0,0 0,6|4,0 4,6|0,3 4,3','I':'0,0 4,0|2,0 2,6|0,6 4,6','J':'4,0 4,5 3,6 1,6 0,5',
'K':'0,0 0,6|4,0 0,3 4,6','L':'0,0 0,6 4,6','M':'0,6 0,0 2,3 4,0 4,6',
'N':'0,6 0,0 4,6 4,0','O':'2,0 0,1 0,5 2,6 4,5 4,1 2,0','P':'0,6 0,0 3,0 4,1 4,2 3,3 0,3',
'Q':'2,0 0,1 0,5 2,6 4,5 4,1 2,0|2,4 4,7','R':'0,6 0,0 3,0 4,1 4,2 3,3 0,3|2,3 4,6',
'S':'4,1 3,0 1,0 0,1 0,2 1,3 3,3 4,4 4,5 3,6 1,6 0,5','T':'0,0 4,0|2,0 2,6',
'U':'0,0 0,5 1,6 3,6 4,5 4,0','V':'0,0 2,6 4,0','W':'0,0 1,6 2,3 3,6 4,0','X':'0,0 4,6|4,0 0,6',
'Y':'0,0 2,3 4,0|2,3 2,6','Z':'0,0 4,0 0,6 4,6',
'0':'2,0 0,1 0,5 2,6 4,5 4,1 2,0','1':'1,1 2,0 2,6|0,6 4,6',
'2':'0,1 1,0 3,0 4,1 4,2 0,6 4,6','3':'0,0 4,0 2,3 4,4 4,5 3,6 0,6',
'4':'3,6 3,0 0,4 4,4','5':'4,0 0,0 0,3 3,3 4,4 4,5 3,6 0,6','6':'4,0 1,0 0,2 0,5 1,6 3,6 4,5 4,4 3,3 0,3',
'7':'0,0 4,0 1,6','8':'1,0 3,0 4,1 3,3 1,3 0,1 1,0|1,3 0,5 1,6 3,6 4,5 3,3',
'9':'4,3 1,3 0,2 0,1 1,0 3,0 4,1 4,5 3,6 0,6',
'.':'2,5.8 2,6',',':'2,5 1,7','!':'2,0 2,4|2,5.8 2,6','?':'0,1 1,0 3,0 4,1 4,2 2,3 2,4|2,5.8 2,6',
'-':'0,3 4,3',':':'2,1.8 2,2|2,4.8 2,5',"'":'2,0 1.5,1','/':'0,6 4,0',
'(':'3,0 1,2 1,4 3,6',')':'1,0 3,2 3,4 1,6','+':'0,3 4,3|2,1 2,5'
}

def make_text(text):
    strokes=[]; x=0; y=0; unsupported=set()
    for char in text[:500]:
        if char=='\n': x=0; y+=10; continue
        if char==' ': x+=4; continue
        glyph=GLYPHS.get(char.upper())
        if glyph is None: unsupported.add(char); x+=6; continue
        for i,part in enumerate(glyph.split('|')):
            points=[]
            for pair in part.split():
                a,b=map(float,pair.split(',')); points.append((x+a+(6-b)*.16,y+b))
            strokes.append(Stroke(f'{char} / {i+1}',points,width=.24))
        x+=6
    if not strokes: raise ValueError('Enter letters A–Z, digits or basic punctuation.')
    pts=[p for s in strokes for p in s.points]; xs,ys=zip(*pts)
    warnings=['Lettering is simple slanted print; lowercase is converted to uppercase.']
    if unsupported: warnings.append('Skipped unsupported characters: '+''.join(sorted(unsupported)))
    return Drawing(strokes,(min(xs),min(ys),max(xs),max(ys)),warnings)
