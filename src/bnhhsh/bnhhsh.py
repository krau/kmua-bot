import json
import pickle
import tempfile
from pathlib import Path

here = Path(__file__).parent


def 破处():
    def 缩(s):
        from pypinyin import pinyin, Style
        q = pinyin(s, style=Style.FIRST_LETTER)
        return ''.join([x[0].lower() for x in q])
    def 丢(词桶, 词表, 痛苦):
        for i in 词表:
            k = 缩(i)
            w = 词桶.setdefault(len(i), {})
            if y:=w.get(k):
                if y[1] > 痛苦:
                    w[k] = [f'{i}', 痛苦]
            else:
                w[k] = [f'{i}', 痛苦]
    with open(here/'data/色情词库.json', encoding='utf8') as f:
        色情词库 = json.load(f)    
    with open(here/'data/色情词库_数据增强.json', encoding='utf8') as f:
        色情词库_数据增强 = json.load(f)
    with open(here/'data/莉沫词库.json', encoding='utf8') as f:
        莉沫词库 = json.load(f)
    with open(here/'data/常用汉字.json', encoding='utf8') as f:
        常用汉字 = json.load(f)
    with open(here/'data/现代汉语常用词表.json', encoding='utf8') as f:
        现代汉语常用词表 = json.load(f)
    词桶 = {
        1: {'i': ['爱', 0.1], 'u': ['幼', 0.1]}
    }
    丢(词桶, 色情词库, 0.001)
    丢(词桶, 莉沫词库, 0.01)
    丢(词桶, 色情词库_数据增强, 0.1)
    丢(词桶, 常用汉字, 0.11)
    丢(词桶, 现代汉语常用词表, 0.2)
    n = max(词桶)
    for i in range(1, n+1):
        词桶.setdefault(i, {})
    with open(Path(tempfile.gettempdir())/'bnhhsh词桶v1.2.2.pkl', 'wb') as f:
        pickle.dump(词桶, f)

q = Path(Path(tempfile.gettempdir())/'bnhhsh词桶v1.2.2.pkl')
if not q.is_file():
    破处()
with open(q, 'rb') as f:
    词桶 = pickle.load(f)

n = max(词桶)

def yndp(target):
    代价 = {-1: 0}
    记录 = {-1: []}
    for x in range(len(target)):
        代价[x] = 2**32
        for k in range(n, 0, -1):
            s = x-k+1
            if s < 0:
                continue
            if c:=词桶[k].get(target[s:x+1]):
                词, 痛苦 = c
                if 代价[x-k]+痛苦 < 代价[x]:
                    代价[x] = 代价[x-k]+痛苦
                    记录[x] = 记录[x-k].copy()
                    记录[x].append((s, x+1, 词))
        if 代价[x-1]+1 < 代价[x]:
            代价[x] = 代价[x-1]+1
            记录[x] = 记录[x-1].copy()
    target = [*target]
    for a, b, c in 记录[len(target)-1][::-1]:
        target[a:b] = c
    return ''.join(target), 代价[len(target)-1]

def dp(target):
    return yndp(target)[0]
