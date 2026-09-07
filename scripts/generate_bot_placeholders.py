"""Original geometric PNG placeholders. No fonts, stock artwork or network assets."""
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1] / 'frontend/public/assets/bots'
NAMES = ('scout','tempo','fork','gambit','castle','tactician','endgame','vanguard','maestro','crown')


def polygon(x,y,points):
    inside=False
    for (ax,ay),(bx,by) in zip(points,points[1:]+points[:1]):
        if (ay>y)!=(by>y) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
            inside=not inside
    return inside


def draw(name,x,y):
    base=70<x<186 and 205<y<222
    if name=='scout': return base or (105<x<151 and 113<y<205) or (x-128)**2+(y-80)**2<31**2
    if name=='tempo': return 57**2<(x-128)**2+(y-128)**2<72**2 or (123<x<133 and 73<y<133) or (126<x<167 and 125<y<135) or (107<x<149 and 38<y<49)
    if name in ('fork','tactician'):
        body=polygon(x,y,[(79,207),(177,207),(158,112),(169,82),(143,35),(120,60),(79,110),(86,130),(119,113),(119,159)])
        spark=name=='tactician' and polygon(x,y,[(193,46),(199,64),(217,70),(199,76),(193,94),(187,76),(169,70),(187,64)])
        return base or body or spark
    if name=='gambit': return base or polygon(x,y,[(82,205),(174,205),(146,140),(165,105),(128,35),(91,105),(111,140)]) and not (abs(x+y-230)<8 and y<126)
    if name=='castle': return base or (87<x<169 and 90<y<205) or (65<x<191 and 60<y<103 and not (87<x<106 and y<82 or 148<x<167 and y<82))
    if name=='vanguard': return polygon(x,y,[(60,60),(128,35),(196,60),(180,160),(128,221),(76,160)]) and not polygon(x,y,[(78,73),(128,55),(178,73),(165,151),(128,195),(91,151)]) or (115<x<141 and 91<y<150)
    if name=='endgame': return base or (109<x<147 and 121<y<205) or (100<x<156 and 82<y<107) or (119<x<137 and 56<y<125)
    if name=='maestro': return base or polygon(x,y,[(89,198),(167,198),(186,87),(151,111),(128,58),(105,111),(70,87)]) or any((x-a)**2+(y-b)**2<10**2 for a,b in [(70,70),(128,38),(186,70)])
    return base or polygon(x,y,[(81,193),(175,193),(200,72),(156,107),(128,45),(100,107),(56,72)])


def chunk(kind,data):
    return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    for name in NAMES:
        rows=[]
        for y in range(256):
            row=bytearray([0])
            for x in range(256):
                alpha=round(255*sum(draw(name,x+dx,y+dy) for dx,dy in ((.25,.25),(.75,.25),(.25,.75),(.75,.75)))/4)
                row.extend((207,183,124,alpha))
            rows.append(bytes(row))
        png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',256,256,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')
        (ROOT/f'{name}.png').write_bytes(png)


if __name__=='__main__': main()
