"""Reproducible *CPU-only* OpenCV benchmark for AI Redraw scene segmentation.

This does NOT benchmark Ollama, GPU inference, or a user's RTX 4070.
Absolute times vary by GitHub runner. No rigid performance assertions.
"""
import time
import statistics

from PIL import Image, ImageDraw
from semantic_redraw import parse_analysis, semantic_masks


def benchmark():
    artwork=Image.new('RGBA',(800,580),'white')
    draw=ImageDraw.Draw(artwork)
    draw.rounded_rectangle((100,80,650,525),55,fill='#dea65d',outline='#574b40',width=14)
    draw.ellipse((230,125,490,380),fill='#476b9f',outline='#283342',width=10)
    draw.rectangle((180,390,525,470),fill='#8ca35d')
    draw.ellipse((525,340,670,485),fill='#d3a78b')
    analysis=parse_analysis({
        'description':'illustration',
        'parts':[
            {'name':'main body','box':[100,100,830,910],'order':1},
            {'name':'round center','box':[285,210,635,675],'order':2},
            {'name':'bottom strip','box':[220,655,685,860],'order':3},
            {'name':'side circle','box':[635,565,840,860],'order':4},
        ],
    })
    results={}
    for mode in ('balanced','quality'):
        # Same pixels, semantic object boxes and reconstruction detail;
        # only OpenCV ROI vs full-frame segmentation changes.
        measurements=[]
        for i in range(3):
            start=time.perf_counter()
            regions,_,_=semantic_masks(artwork,analysis,'medium',profile=mode)
            elapsed=time.perf_counter()-start
            if i>0:measurements.append(elapsed)
        results[mode]=statistics.median(measurements)
        print(f'CPU_ONLY_OPENCV_BENCHMARK {mode} {results[mode]:.4f}s '
              f'({regions.size[0]}x{regions.size[1]} segmentation grid)',
              flush=True)
    if results['balanced']>0:
        ratio=results['quality']/results['balanced']
        print(f'CPU_ONLY_OPENCV_BENCHMARK full_to_balanced_ratio {ratio:.2f}x',flush=True)
    print('Ollama model latency: NOT measured in CI.',flush=True)


if __name__=='__main__':
    benchmark()
