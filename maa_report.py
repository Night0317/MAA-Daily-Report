import re
import os
import sys
import json
import shutil
import hashlib
import traceback
import html as html_lib
from collections import defaultdict
from datetime import datetime

# ================= 配置区 =================
SCHEMA_VERSION = 2  # 数据结构版本，升级后自动重建历史库

if getattr(sys, 'frozen', False):
    SCRIPT_DIR = os.path.dirname(sys.executable)
    # PyInstaller 打包的资源（images/ 等）在临时解压目录
    RESOURCE_DIR = sys._MEIPASS
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    RESOURCE_DIR = SCRIPT_DIR

# 数据目录：用户应用数据，不在 exe 旁边生成文件
DATA_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'MAA作战报告')
os.makedirs(DATA_DIR, exist_ok=True)

STATE_PATH  = os.path.join(DATA_DIR, "history.json")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
# HTML 在内存中生成，不写文件
REPORT_HTML_CACHE = {'content': ''}

# 常见 MAA 安装路径（自动探测用）
COMMON_MAA_PATTERNS = [
    # 桌面
    os.path.join(os.path.expanduser("~"), "Desktop", "MAA*", "debug", "gui.log"),
    os.path.join(os.path.expanduser("~"), "Desktop", "MAAA*", "debug", "gui.log"),
    # 默认安装目录
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "MAA", "debug", "gui.log"),
    # D盘常见位置
    os.path.join("D:\\", "MAA*", "debug", "gui.log"),
    os.path.join("D:\\", "Program Files", "MAA*", "debug", "gui.log"),
]


def detect_maa_log():
    """自动探测 MAA 的 gui.log 路径"""
    import glob
    for pattern in COMMON_MAA_PATTERNS:
        try:
            matches = glob.glob(pattern)
            if matches:
                # 取最新修改的那个
                matches.sort(key=os.path.getmtime, reverse=True)
                return matches[0]
        except OSError:
            continue
    return None


def load_config():
    """加载配置文件，返回 log_path"""
    # 1. 先读 config.json
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            p = cfg.get('log_path', '').strip()
            if p and os.path.exists(p):
                return p
        except Exception:
            pass
    # 2. 自动探测
    detected = detect_maa_log()
    if detected:
        # 自动写入 config.json 方便下次
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump({'log_path': detected}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return detected
    # 3. 都没找到
    return None


def save_config(log_path):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump({'log_path': log_path}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


LOG_PATH = load_config()
LEGACY_STATE_CANDIDATES = [
    os.path.join(SCRIPT_DIR, "MAA_history.json"),
    os.path.join(os.path.expanduser("~"), "Desktop", "MAA_history.json"),
]
# =========================================

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def log(*a, **kw):
    try:
        print(*a, **kw, flush=True)
    except Exception:
        pass


# ---------- 正则 ----------
REGEX_TS            = re.compile(r'\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)\]')
REGEX_DATE_FALLBACK = re.compile(r'\[(\d{4}-\d{2}-\d{2})\]')
REGEX_STAGE_DROP    = re.compile(r'(.*?)\s*掉落统计\s*[:：]?')
REGEX_TIMES         = re.compile(r'当前次数\s*[:：]\s*(\d+)')
REGEX_SANITY        = re.compile(r'开始行动\s*(?:\d+~\d+|\d+)\s*次\s*[,，]\s*-\s*(\d+)\s*理智')
REGEX_ROGUE         = re.compile(r'肉鸽结算\s*[:：]\s*(✓|✗)\s*\((.*?)\)')
REGEX_RECRUIT       = re.compile(r'已确认招募\s*(\d+)')
REGEX_DROP_ITEM     = re.compile(
    r'^(?P<name>[^:：\n]+?)\s*[:：]\s*(?P<qty>\d+(?:\.\d+)?[kKwW]?)'
    r'(?:\s*[（(]\s*[+＋]\s*(?P<extra>\d+(?:\.\d+)?[kKwW]?)\s*[)）])?\s*$'
)
# 肉鸽详情（无时间戳的连续行）
REGEX_ROGUE_EXPLORE = re.compile(r'探索\s*[:：]\s*(\d+)\s*层\s*(\d+)\s*步')
REGEX_ROGUE_BATTLE  = re.compile(r'战斗\s*[:：]\s*(\d+)\s*/\s*(\d+)\s*紧急/\s*(\d+)\s*BOSS')
REGEX_ROGUE_CREW    = re.compile(r'招募\s*[:：]\s*(\d+)\s*收藏品\s*[:：]\s*(\d+)')
REGEX_ROGUE_SCORE   = re.compile(r'得分\s*[:：]\s*(\d+)')
REGEX_ROGUE_EXP     = re.compile(r'Exp\s*[:：]\s*\+(\d+)\s*Skill\s*[:：]\s*\+(\d+)')

ENGLISH_ITEM_WHITELIST = {'RMA70-12', 'RMA70-24', 'D32钢'}
ITEM_BLACKLIST = {
    '最快截图耗时', '剩余时间', '专精等级', '当前次数', '开始行动',
    '理智', '关卡', '行动', '掉落统计', '已用时间', 'ID', 'Index',
}

ITEM_EMOJI = {
    '龙门币': '💰', '合成玉': '💎', '源石': '🔷',
    '固源岩': '🪨', '装置': '⚙️', '异铁': '🔩',
    '酮': '🧫', '糖': '🍬', '聚酸酯': '🧪', '醇': '🍷',
    'RMA70': '🌿', '扭转醇': '🌀', '三水锰矿': '💠',
    '炽合金': '🔥', '晶体元件': '🔮', '凝胶': '🟡',
    '环烃聚质': '🧊', '电极单元': '🔋', '转质盐': '🧂',
    '声望': '🏆', '家具': '🛋️', '作战记录': '📘',
    '芯片': '🧩', '碳素': '🪵', '酯原料': '🧴',
    '溶剂': '🫗', '研磨石': '🪨', '削骸体': '💀',
    '凝固燃料': '⛽', '半自然溶剂': '🧪',
}

# 材料名 → PRTS torappu CDN 图片文件名
ITEM_IMG_MAP = {
    # 货币
    '龙门币': 'GOLD', '赤金': 'MTL_GOLD3', '合成玉': 'DIAMOND_SHD',
    '声望': 'EXP_PLAYER', '采购凭证': 'EXGG_SHD', '家具': 'COIN_FURN', '家具零件': 'COIN_FURN',
    '失效的记录': 'act55side_token_record',
    # 经验书
    '基础作战记录': 'sprite_exp_card_t1', '初级作战记录': 'sprite_exp_card_t2',
    '中级作战记录': 'sprite_exp_card_t3', '高级作战记录': 'sprite_exp_card_t4',
    # 技能书
    '技巧概要·卷1': 'MTL_SKILL1', '技巧概要·卷2': 'MTL_SKILL2', '技巧概要·卷3': 'MTL_SKILL3',
    # 芯片
    '先锋芯片': 'MTL_ASC_PIO1', '先锋芯片组': 'MTL_ASC_PIO2',
    '狙击芯片': 'MTL_ASC_SNP1', '狙击芯片组': 'MTL_ASC_SNP2',
    '术师芯片': 'MTL_ASC_CST1', '术师芯片组': 'MTL_ASC_CST2',
    '重装芯片': 'MTL_ASC_TNK1', '重装芯片组': 'MTL_ASC_TNK2',
    '医疗芯片': 'MTL_ASC_MED1', '医疗芯片组': 'MTL_ASC_MED2',
    '辅助芯片': 'MTL_ASC_SUP1', '辅助芯片组': 'MTL_ASC_SUP2',
    '特种芯片': 'MTL_ASC_SPC1', '特种芯片组': 'MTL_ASC_SPC2',
    '近卫芯片': 'MTL_ASC_GRD1', '近卫芯片组': 'MTL_ASC_GRD2',
    # 岩石类
    '源岩': 'MTL_SL_G1', '固源岩': 'MTL_SL_G2', '固源岩组': 'MTL_SL_G3', '提纯源岩': 'MTL_SL_G4',
    # 异铁类
    '异铁碎片': 'MTL_SL_IRON1', '异铁': 'MTL_SL_IRON2', '异铁组': 'MTL_SL_IRON3', '异铁块': 'MTL_SL_IRON4',
    # 装置类
    '破损装置': 'MTL_SL_BOSS1', '装置': 'MTL_SL_BOSS2', '全新装置': 'MTL_SL_BOSS3', '改量装置': 'MTL_SL_BOSS4',
    # 聚酸酯类
    '酯原料': 'MTL_SL_RUSH1', '聚酸酯': 'MTL_SL_RUSH2', '聚酸酯组': 'MTL_SL_RUSH3', '聚酸酯块': 'MTL_SL_RUSH4',
    # 糖/酮类
    '代糖': 'MTL_SL_STRG1', '糖': 'MTL_SL_STRG2', '双酮': 'MTL_SL_KETONE1', '酮凝集': 'MTL_SL_KETONE2',
    # 醇类
    '扭转醇': 'MTL_SL_ALCOHOL1', '白马醇': 'MTL_SL_ALCOHOL2',
    # 锰矿类
    '轻锰矿': 'MTL_SL_MANGANESE1', '三水锰矿': 'MTL_SL_MANGANESE2',
    # 研磨石类
    '研磨石': 'MTL_SL_PG1', '五水研磨石': 'MTL_SL_PG2',
    # 凝胶类
    '凝胶': 'MTL_SL_PGEL3', '聚合凝胶': 'MTL_SL_PGEL4',
    # 炽合金类
    '炽合金': 'MTL_SL_IAM3', '炽合金块': 'MTL_SL_IAM4',
    # 晶体类
    '晶体元件': 'MTL_SL_OC3', '晶体电路': 'MTL_SL_OC4',
    # 第二模块新材料
    '环烃聚质': 'MTL_SL_HT', '环烃预制体': 'MTL_SL_HTT',
    '电极单元': 'MTL_SL_DJ', '聚能动力单元': 'MTL_SL_DJ4',
    '液化高能气体': 'MTL_SL_YHT', '液化醚吸聚体': 'MTL_SL_YHT4',
    '类凝结核': 'MTL_SL_JH', '手性屈光体': 'MTL_SL_QGT',
    '褐素纤维': 'MTL_SL_XW', '固化纤维板': 'MTL_SL_XWB',
    '转质盐组': 'MTL_SL_ZY', '转质盐聚块': 'MTL_SL_ZYK',
    '切削原液': 'MTL_SL_PLCF', '化合切削液': 'MTL_SL_CCF',
    '精炼溶剂': 'MTL_SL_RS', '半自然溶剂': 'MTL_SL_SS',
    # RMA/D32/高级
    'RMA70-12': 'MTL_SL_RMA7012', 'RMA70-24': 'MTL_SL_RMA7024', 'D32钢': 'MTL_SL_DS',
    '双极纳米片': 'MTL_SL_BN', '聚合剂': 'MTL_SL_PP', '晶体电子单元': 'MTL_SL_OEU',
    # 第二模块新材料补充
    '重相位对映体': 'MTL_SL_DYT', '烧结核凝晶': 'MTL_SL_SHJ',
}

PRTS_IMG_URL = 'https://torappu.prts.wiki/assets/item_icon/{name}.png'


def item_img_url(name: str) -> str:
    """获取材料图片路径：优先本地 images/ 文件夹，否则用 CDN"""
    fname = ITEM_IMG_MAP.get(name)
    if not fname:
        return ''
    # 先找 exe 同目录的 images（用户可替换），再找打包进 exe 的 images
    for base in (SCRIPT_DIR, RESOURCE_DIR):
        local_path = os.path.join(base, 'images', f'{fname}.png')
        if os.path.exists(local_path):
            return f'images/{fname}.png'
    return PRTS_IMG_URL.format(name=fname)


_B64_CACHE = {}
_CSS_IMAGES = []  # 收集需要内嵌的图片 CSS

def item_img_tag(name: str, size: int = 40) -> str:
    """生成材料图标：用 CSS class 引用背景图（base64 只写一次）"""
    fname = ITEM_IMG_MAP.get(name)
    if not fname:
        return f'<span style="width:{size}px;height:{size}px;border-radius:50%;background:var(--bg2);display:inline-block"></span>'
    if fname not in _B64_CACHE:
        for base in (SCRIPT_DIR, RESOURCE_DIR):
            img_path = os.path.join(base, 'images', f'{fname}.png')
            if os.path.exists(img_path):
                try:
                    import base64
                    with open(img_path, 'rb') as f:
                        b64 = base64.b64encode(f.read()).decode()
                    _B64_CACHE[fname] = b64
                    _CSS_IMAGES.append(f'.mi-{fname}{{background-image:url(data:image/png;base64,{b64})}}')
                    break
                except Exception:
                    pass
        if fname not in _B64_CACHE:
            _B64_CACHE[fname] = None
    if _B64_CACHE.get(fname):
        return (f'<span class="mi mi-{fname}" style="width:{size}px;height:{size}px" '
                f'alt="{esc(name)}"></span>')
    url = item_img_url(name)
    if url:
        return (f'<img src="{url}" alt="{esc(name)}" '
                f'style="width:{size}px;height:{size}px;border-radius:50%;object-fit:cover;background:var(--bg2);">')
    return f'<span style="width:{size}px;height:{size}px;border-radius:50%;background:var(--bg2);display:inline-block"></span>'

WEEKDAY_CN = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']


# ---------- 工具 ----------
def esc(s):
    return html_lib.escape(str(s))


def fmt_qty(q: float) -> str:
    if q >= 10000:
        s = f"{q / 10000:.2f}".rstrip('0').rstrip('.')
        return f"{s}w"
    if abs(q - round(q)) < 1e-6:
        return str(int(round(q)))
    return f"{q:.1f}"


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


def item_emoji(name: str) -> str:
    for k, v in ITEM_EMOJI.items():
        if k in name:
            return v
    return '📦'


def is_valid_item(name: str) -> bool:
    name = name.strip()
    if not name or len(name) > 20:
        return False
    if name in ITEM_BLACKLIST:
        return False
    if name in ENGLISH_ITEM_WHITELIST:
        return True
    if not re.match(r'^[\u4e00-\u9fa5]', name):
        return False
    if not re.match(r'^[\u4e00-\u9fa5A-Za-z0-9\-·]+$', name):
        return False
    return True


def is_valid_stage(s: str) -> bool:
    if not s or len(s) > 20:
        return False
    if re.match(r'^[\d\s]+$', s):
        return False
    return True


def clean_stage(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r'\[[^\]]*\]', '', s)
    s = re.sub(r'<[^>]*>', '', s)
    return s.strip()


def parse_drop_value(v: str) -> float:
    if v and v[-1] in 'kK':
        return float(v[:-1]) * 1000
    if v and v[-1] in 'wW':
        return float(v[:-1]) * 10000
    return float(v)


def strip_log_prefix(line: str) -> str:
    s = re.sub(r'^\s*(?:\[[^\]]*\]\s*)+', '', line)
    s = re.sub(r'^\s*(?:<[^>]*>\s*)+', '', s)
    return s.strip()


# ---------- 自动迁移旧历史库 ----------
def migrate_legacy_state():
    if os.path.exists(STATE_PATH):
        return
    for src in LEGACY_STATE_CANDIDATES:
        if not os.path.exists(src):
            continue
        if os.path.abspath(src) == os.path.abspath(STATE_PATH):
            continue
        try:
            os.makedirs(os.path.dirname(STATE_PATH) or '.', exist_ok=True)
            shutil.copy2(src, STATE_PATH)
            log(f"📦 自动迁移历史库：")
            log(f"   源  ：{src}")
            log(f"   目标：{STATE_PATH}")
            return
        except Exception as e:
            log(f"⚠️ 迁移历史库失败（{src}）：{e}")


# ---------- 历史库 ----------
class HistoryState:
    def __init__(self, path):
        self.path = path
        self.events = []
        self.fingerprints = set()
        self.file_offsets = {}  # {文件路径: (大小, 修改时间, offset)}
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            log("📦 首次运行：尚未发现历史库，本次会自动创建")
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            ver = data.get('version', 1)
            if ver != SCHEMA_VERSION:
                backup = self.path + f'.v{ver}.bak'
                shutil.copy2(self.path, backup)
                log(f"📦 检测到历史库版本 v{ver}（当前需要 v{SCHEMA_VERSION}）")
                log(f"   已备份旧库到：{backup}")
                log(f"   将重新解析全部日志...")
                return
            self.events = data.get('events', []) or []
            self.fingerprints = set(data.get('fingerprints', []) or [])
            self.file_offsets = data.get('file_offsets', {}) or {}
            days = len({e['ts'][:10] for e in self.events if e.get('ts')})
            log(f"📦 加载历史库：{len(self.events)} 条事件 / 覆盖 {days} 天")
        except Exception as e:
            log(f"⚠️ 历史库读取失败（{e}），将重新开始")

    def save(self):
        os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump({
                'version': SCHEMA_VERSION,
                'fingerprints': list(self.fingerprints),
                'events': self.events,
                'file_offsets': self.file_offsets,
            }, f, ensure_ascii=False, indent=1)

    def add(self, ts, kind, payload) -> bool:
        if not ts:
            return False
        fp_src = f"{ts}|{kind}|{json.dumps(payload, sort_keys=True, ensure_ascii=False)}"
        fp = hashlib.md5(fp_src.encode('utf-8')).hexdigest()
        if fp in self.fingerprints:
            return False
        self.fingerprints.add(fp)
        self.events.append({'ts': ts, 'kind': kind, 'payload': payload})
        return True


# ---------- 日志发现 ----------
def find_log_files():
    log_dir = os.path.dirname(LOG_PATH)
    if not os.path.isdir(log_dir):
        return []
    candidates = []
    for fname in os.listdir(log_dir):
        low = fname.lower()
        if ('gui' in low or 'maa' in low) and (
            low.endswith('.log') or
            '.log.' in low or
            low.endswith('.log.bak') or
            low.endswith('.bak.log')
        ):
            try:
                candidates.append(os.path.join(log_dir, fname))
            except OSError:
                pass
    candidates.sort(key=lambda p: os.path.getmtime(p))
    return candidates


# ---------- 单文件解析 ----------
def parse_one_log(log_file: str, state: HistoryState) -> dict:
    stats = {'sanity': 0, 'rogue': 0, 'recruit': 0, 'drop_block': 0}

    # 增量解析：检查文件是否有变化
    try:
        fstat = os.stat(log_file)
        fsize = fstat.st_size
        fmtime = fstat.st_mtime
    except OSError:
        fsize, fmtime = 0, 0

    prev = state.file_offsets.get(log_file)
    if prev and prev[0] == fsize and prev[1] == fmtime:
        log(f"   ⏭️ 跳过（无变化）: {os.path.basename(log_file)}")
        return stats

    # 掉落块状态
    current_stage = None
    in_drop_block = False
    block_ts = None
    block_items = {}
    block_times = 0

    # 肉鸽详情状态（结算行后面跟随3-5行无时间戳的详情）
    in_rogue_detail = False
    rogue_ts = None
    rogue_payload = None

    def flush_drop_block():
        nonlocal in_drop_block, current_stage, block_ts, block_items, block_times
        if in_drop_block and current_stage and block_ts and (block_times or block_items):
            payload = {
                'stage': current_stage,
                'times': block_times,
                'items': {k: [round(v['base'], 3), round(v['extra'], 3)] for k, v in block_items.items()},
            }
            if state.add(block_ts, 'drop_block', payload):
                stats['drop_block'] += 1
        in_drop_block = False
        current_stage = None
        block_ts = None
        block_items = {}
        block_times = 0

    def flush_rogue_detail():
        nonlocal in_rogue_detail, rogue_ts, rogue_payload
        if in_rogue_detail and rogue_payload is not None:
            if state.add(rogue_ts, 'rogue', rogue_payload):
                stats['rogue'] += 1
        in_rogue_detail = False
        rogue_ts = None
        rogue_payload = None

    # 从上次 offset 开始读（如果文件没变大就从头读）
    start_offset = 0
    if prev and fsize >= prev[0]:
        start_offset = prev[2] if prev[2] <= fsize else 0

    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        if start_offset > 0:
            f.seek(start_offset)
        for raw in f:
            line = raw.rstrip('\n')
            stripped = line.strip()
            if not stripped:
                continue

            # 时间戳提取
            ts_match = REGEX_TS.search(line)
            if ts_match:
                line_ts = ts_match.group(1)
                # 遇到新的时间戳行，说明之前的无时间戳详情块结束了
                flush_drop_block()
                flush_rogue_detail()
            else:
                # 无时间戳的行：只有在详情块内才处理，否则跳过
                if in_drop_block or in_rogue_detail:
                    line_ts = None  # 沿用块的时间戳
                else:
                    continue

            # ---- 肉鸽结算（有时间戳）----
            if line_ts:
                m = REGEX_ROGUE.search(line)
                if m:
                    flush_drop_block()
                    in_rogue_detail = True
                    rogue_ts = line_ts
                    rogue_payload = {
                        'result': m.group(1),
                        'level': m.group(2).strip(),
                        'floors': 0, 'steps': 0,
                        'battles': 0, 'urgent': 0, 'boss': 0,
                        'recruits': 0, 'collectibles': 0,
                        'score': 0, 'exp': 0, 'skill': 0,
                    }
                    continue

            # ---- 肉鸽详情行（无时间戳）----
            if in_rogue_detail and rogue_payload is not None:
                cleaned = strip_log_prefix(stripped)
                m = REGEX_ROGUE_EXPLORE.match(cleaned)
                if m:
                    rogue_payload['floors'] = int(m.group(1))
                    rogue_payload['steps'] = int(m.group(2))
                    continue
                m = REGEX_ROGUE_BATTLE.match(cleaned)
                if m:
                    rogue_payload['battles'] = int(m.group(1))
                    rogue_payload['urgent'] = int(m.group(2))
                    rogue_payload['boss'] = int(m.group(3))
                    continue
                m = REGEX_ROGUE_CREW.match(cleaned)
                if m:
                    rogue_payload['recruits'] = int(m.group(1))
                    rogue_payload['collectibles'] = int(m.group(2))
                    continue
                m = REGEX_ROGUE_SCORE.match(cleaned)
                if m:
                    rogue_payload['score'] = int(m.group(1))
                    continue
                m = REGEX_ROGUE_EXP.match(cleaned)
                if m:
                    rogue_payload['exp'] = int(m.group(1))
                    rogue_payload['skill'] = int(m.group(2))
                    continue
                # 如果是其他有时间戳的行，flush 会在上面处理

            # ---- 理智（有时间戳）----
            if line_ts:
                m = REGEX_SANITY.search(line)
                if m:
                    if state.add(line_ts, 'sanity', {'value': int(m.group(1))}):
                        stats['sanity'] += 1
                    continue

            # ---- 公招（有时间戳）----
            if line_ts:
                m = REGEX_RECRUIT.search(line)
                if m:
                    if state.add(line_ts, 'recruit', {'value': int(m.group(1))}):
                        stats['recruit'] += 1
                    continue

            # ---- 掉落统计（有时间戳）----
            if line_ts:
                m = REGEX_STAGE_DROP.search(line)
                if m:
                    stage = clean_stage(m.group(1))
                    if is_valid_stage(stage):
                        in_drop_block = True
                        current_stage = stage
                        block_ts = line_ts
                        block_items = {}
                        block_times = 0
                    continue

            # ---- 掉落块内的行（无时间戳）----
            if in_drop_block:
                m = REGEX_TIMES.search(stripped)
                if m:
                    block_times += int(m.group(1))
                    continue
                cleaned = strip_log_prefix(stripped)
                m = REGEX_DROP_ITEM.match(cleaned)
                if m:
                    name = m.group('name').strip()
                    if is_valid_item(name):
                        qty = parse_drop_value(m.group('qty'))
                        extra = parse_drop_value(m.group('extra')) if m.group('extra') else 0.0
                        if qty < 1e9 and extra < 1e9:
                            if name not in block_items:
                                block_items[name] = {'base': 0.0, 'extra': 0.0}
                            block_items[name]['base'] += qty
                            block_items[name]['extra'] += extra

    flush_drop_block()
    flush_rogue_detail()

    # 记录文件偏移量，下次增量读取
    state.file_offsets[log_file] = [fsize, fmtime, fsize]
    return stats


def parse_all_logs(state: HistoryState) -> bool:
    logs = find_log_files()
    if not logs:
        log(f"❌ 在 {os.path.dirname(LOG_PATH)} 下没有找到任何日志文件")
        log("   请确认 MAA 路径是否正确，或先运行一次 MAA 生成 gui.log。")
        return False

    log(f"🔍 发现 {len(logs)} 个日志文件（按老→新）：")
    for p in logs:
        log(f"   · {os.path.basename(p)}")

    total = {'sanity': 0, 'rogue': 0, 'recruit': 0, 'drop_block': 0}
    for p in logs:
        try:
            stats = parse_one_log(p, state)
            for k, v in stats.items():
                total[k] += v
            log(f"   → {os.path.basename(p)}：理智 {stats['sanity']} / "
                f"肉鸽 {stats['rogue']} / 公招 {stats['recruit']} / "
                f"掉落块 {stats['drop_block']}")
        except Exception as e:
            log(f"   ⚠️ {os.path.basename(p)} 解析失败：{e}")
            traceback.print_exc()

    log(f"✅ 本次新增：理智 {total['sanity']} / 肉鸽 {total['rogue']} / "
        f"公招 {total['recruit']} / 掉落块 {total['drop_block']}")
    log(f"   累计：{len(state.events)} 条事件")

    if sum(total.values()) == 0 and not state.events:
        log("")
        log("💡 没有任何事件被解析，报告将为空。可能原因：")
        log("   1. MAA 日志已被轮转清空")
        log("   2. 日志格式发生变化 / 路径配置错误")
    return True


# ---------- 聚合 ----------
def aggregate_events(state: HistoryState):
    daily = defaultdict(lambda: {
        'drops': defaultdict(lambda: {
            'times': 0,
            'items': defaultdict(lambda: {'base': 0.0, 'extra': 0.0}),
        }),
        'sanity': 0,
        'rogue': [],
        'recruit': 0,
    })
    for ev in state.events:
        ts = ev.get('ts') or ''
        if len(ts) < 10:
            continue
        date = ts[:10]
        kind = ev.get('kind')
        p = ev.get('payload') or {}
        if kind == 'sanity':
            daily[date]['sanity'] += p.get('value', 0)
        elif kind == 'recruit':
            daily[date]['recruit'] += p.get('value', 0)
        elif kind == 'rogue':
            daily[date]['rogue'].append(p)
        elif kind == 'drop_block':
            stage = p.get('stage')
            if not stage:
                continue
            info = daily[date]['drops'][stage]
            info['times'] += p.get('times', 0)
            for name, pair in (p.get('items') or {}).items():
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    base, extra = pair
                else:
                    base, extra = 0.0, 0.0
                info['items'][name]['base'] += float(base)
                info['items'][name]['extra'] += float(extra)
    return daily


# ---------- HTML ----------
CSS = """
:root{
  --bg:#0f0f14;--bg2:#181822;--card:#1a1a26;--card-hover:#22222f;
  --text:#e8e8f0;--text-muted:#707088;--border:#252535;
  --purple:#8b5cf6;--purple-light:#a78bfa;
  --green:#22c55e;--yellow:#eab308;--red:#ef4444;
}
*{box-sizing:border-box;margin:0;padding:0}
body{padding:16px 12px 40px;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  font-size:13px;line-height:1.5;color:var(--text);background:var(--bg);
  -webkit-font-smoothing:antialiased;}
.container{max-width:960px;margin:0 auto}
header{margin-bottom:14px;display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:8px}
h1{font-size:18px;font-weight:700;letter-spacing:-.3px}
.meta{color:var(--text-muted);font-size:11px}

/* 顶部统计栏 */
.stats-bar{background:var(--card);border:1px solid var(--border);border-radius:10px;
  padding:12px 20px;display:flex;justify-content:space-around;flex-wrap:wrap;gap:8px;margin-bottom:12px}
.stat-item{text-align:center}
.stat-label{color:var(--text-muted);font-size:10px;margin-bottom:1px}
.stat-value{font-size:18px;font-weight:700;letter-spacing:-.3px}

section{margin-bottom:12px}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px}
.card-title{font-size:13px;font-weight:600;margin-bottom:10px;display:flex;align-items:center;justify-content:space-between}

/* 热力图 */
.heatmap-cols{display:grid;gap:2px}
.heat-cell{width:11px;height:11px;border-radius:2px;background:var(--bg2)}
.heat-cell.l1{background:#2a1f4a}
.heat-cell.l2{background:#4c3a7c}
.heat-cell.l3{background:#6d4fc0}
.heat-cell.l4{background:#8b5cf6}
.heat-legend{display:flex;align-items:center;gap:3px;justify-content:flex-end;font-size:10px;color:var(--text-muted);margin-top:6px}
.heat-legend .heat-cell{width:9px;height:9px}
.month-labels{display:grid;gap:2px;font-size:9px;color:var(--text-muted);margin-bottom:2px}
.month-labels span{white-space:nowrap}

/* 柱状图 */
.bar-chart{display:flex;align-items:flex-end;gap:6px;height:140px;padding:10px 0 0;border-bottom:1px solid var(--border)}
.bar-col{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;min-width:0;gap:2px}
.bar{width:100%;max-width:32px;background:var(--purple);border-radius:3px 3px 0 0;min-height:2px}
.bar-label{font-size:9px;color:var(--text-muted);white-space:nowrap}
.bar-val{font-size:10px;color:var(--text-muted);font-weight:600}

/* 材料网格 */
.items-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(72px,1fr));gap:8px}
.item-cell{text-align:center;padding:6px 2px;border-radius:6px;transition:background .15s}
.item-cell:hover{background:var(--card-hover)}
.item-icon{width:40px;height:40px;margin:0 auto 4px}
.item-icon img{display:block;width:100%;height:100%}
.item-name{font-size:10px;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.item-qty{font-size:12px;font-weight:700;margin-top:1px}

/* 关卡排名 */
.rank-row{display:grid;grid-template-columns:70px 1fr 50px;gap:8px;align-items:center;padding:3px 0;font-size:12px}
.rank-bar-wrap{background:var(--bg2);height:14px;border-radius:3px;overflow:hidden}
.rank-bar{height:100%;background:var(--purple);border-radius:3px}
.rank-num{text-align:right;font-weight:600;font-variant-numeric:tabular-nums;font-size:11px}
.rank-name{font-size:11px;color:var(--text-muted)}

/* 肉鸽 */
.rogue-hero{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:8px;text-align:center}
.rogue-hero-item{padding:8px;background:var(--bg2);border-radius:6px}
.rogue-hero-num{font-size:20px;font-weight:700}
.rogue-hero-num.win{color:var(--green)}
.rogue-hero-num.lose{color:var(--red)}
.rogue-hero-num.rate{color:var(--purple-light)}
.rogue-hero-label{font-size:10px;color:var(--text-muted);margin-top:1px}

table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:5px 8px;text-align:left;border-bottom:1px solid var(--border)}
th{color:var(--text-muted);font-weight:600;font-size:10px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tr:hover td{background:var(--card-hover)}

.badge{display:inline-block;padding:1px 7px;border-radius:8px;font-size:10px;font-weight:500}
.badge.sanity{background:rgba(139,92,246,.15);color:var(--purple-light)}
.badge.battle{background:rgba(234,179,8,.15);color:var(--yellow)}
.badge.recruit{background:rgba(34,197,94,.15);color:var(--green)}
.badge.rogue{background:rgba(139,92,246,.15);color:var(--purple-light)}

.day-card{background:var(--card);border:1px solid var(--border);border-radius:8px;margin-bottom:6px;overflow:hidden}
.day-card>summary{list-style:none;cursor:pointer;padding:8px 12px;display:flex;align-items:center;gap:8px;font-size:12px;font-weight:500;user-select:none}
.day-card>summary:hover{background:var(--card-hover)}
.day-card>summary::-webkit-details-marker{display:none}
.day-card>summary::before{content:"›";font-size:14px;color:var(--text-muted)}
.day-card[open]>summary::before{transform:rotate(90deg)}
.day-content{padding:0 12px 12px}
.day-content h3{font-size:10px;margin:10px 0 4px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px}

.pill{display:inline-block;padding:1px 6px;margin:1px;background:var(--bg2);border:1px solid var(--border);border-radius:4px;font-size:10px;white-space:nowrap}
.pill .qty{color:var(--purple-light);font-weight:600;margin-left:3px}

.timeline{position:relative;padding-left:14px}
.timeline::before{content:"";position:absolute;left:5px;top:4px;bottom:4px;width:1px;background:var(--border)}
.tl-item{position:relative;padding:3px 0 3px 8px;font-size:11px}
.tl-item::before{content:"";position:absolute;left:-16px;top:8px;width:6px;height:6px;border-radius:50%;background:var(--purple)}
.tl-item.win::before{background:var(--green)}
.tl-item.lose::before{background:var(--red)}
.tl-time{color:var(--text-muted);font-size:9px;margin-right:5px}

select{background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:5px;padding:3px 6px;font-size:11px}

@media (max-width:640px){
  body{padding:8px 6px 30px}
  h1{font-size:16px}
  .stats-bar{padding:8px}
  .stat-value{font-size:16px}
  .items-grid{grid-template-columns:repeat(auto-fill,minmax(60px,1fr))}
}
"""


def generate_html(daily_data: dict, state: HistoryState):
    dates = sorted(daily_data.keys()) if daily_data else []

    total_sanity  = sum(d['sanity'] for d in daily_data.values()) if daily_data else 0
    total_recruit = sum(d['recruit'] for d in daily_data.values()) if daily_data else 0
    total_rogue   = sum(len(d['rogue']) for d in daily_data.values()) if daily_data else 0
    total_battles = sum(
        info['times'] for d in daily_data.values() for info in d['drops'].values()
    ) if daily_data else 0

    # 肉鸽统计
    all_rogue = []
    for d in daily_data.values():
        all_rogue.extend(d['rogue'])
    rogue_wins = [r for r in all_rogue if r.get('result') == '✓']
    rogue_loses = [r for r in all_rogue if r.get('result') == '✗']
    rogue_win_rate = (len(rogue_wins) / len(all_rogue) * 100) if all_rogue else 0
    by_level = defaultdict(list)
    for r in all_rogue:
        by_level[r.get('level', '?')].append(r)
    avg_score = sum(r.get('score', 0) for r in rogue_wins) / len(rogue_wins) if rogue_wins else 0
    avg_floors_all = sum(r.get('floors', 0) for r in all_rogue) / len(all_rogue) if all_rogue else 0
    all_rogue_sorted = sorted(all_rogue, key=lambda r: r.get('ts', '')) if all_rogue else []
    recent_rogue = all_rogue_sorted[-10:]

    # 材料统计
    all_items = defaultdict(float)
    item_by_stage = defaultdict(lambda: defaultdict(float))  # item -> stage -> qty
    for d in (daily_data or {}).values():
        for stage, info in d['drops'].items():
            for name, q in info['items'].items():
                qty = q['base'] + q['extra']
                all_items[name] += qty
                item_by_stage[name][stage] += qty
    top_items = sorted(all_items.items(), key=lambda kv: -kv[1])

    # 按月统计理智（用于柱状图）
    monthly_sanity = defaultdict(int)
    for d in dates:
        monthly_sanity[d[:7]] += daily_data[d]['sanity']
    months_sorted = sorted(monthly_sanity.keys())
    max_monthly = max(monthly_sanity.values()) if monthly_sanity else 1

    # 热力图数据（按天理智，分4级）
    max_daily_sanity = max((daily_data[d]['sanity'] for d in dates), default=1) if dates else 1
    sanity_by_day = {d: daily_data[d]['sanity'] for d in dates}

    H = []
    _B64_CACHE.clear()
    _CSS_IMAGES.clear()
    H.append('<!DOCTYPE html><html lang="zh-CN"><head>')
    H.append('<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">')
    H.append('<title>MAA 作战日报</title>')
    H.append(f'<style>{CSS}')
    H.append('.mi{display:inline-block;border-radius:50%;object-fit:cover;background-size:cover;background-position:center;background-color:var(--bg2);flex-shrink:0}')
    H.append('</style></head><body><div class="container">')

    # ---- 头部 ----
    H.append('<header>')
    H.append('  <h1>MAA 作战日报</h1>')
    H.append(f'  <div class="meta">{datetime.now().strftime("%Y-%m-%d %H:%M")} · {len(state.events)} 条事件</div>')
    H.append('</header>')

    # ---- 顶部统计栏 ----
    H.append('<div class="stats-bar">')
    H.append(f'  <div class="stat-item"><div class="stat-label">场次</div><div class="stat-value">{total_battles:,}</div></div>')
    H.append(f'  <div class="stat-item"><div class="stat-label">理智消耗</div><div class="stat-value">{total_sanity:,}</div></div>')
    H.append(f'  <div class="stat-item"><div class="stat-label">公招确认</div><div class="stat-value">{total_recruit}</div></div>')
    H.append(f'  <div class="stat-item"><div class="stat-label">肉鸽结算</div><div class="stat-value">{total_rogue}</div></div>')
    H.append(f'  <div class="stat-item"><div class="stat-label">材料种类</div><div class="stat-value">{len(all_items)}</div></div>')
    H.append('</div>')

    # ---- 周度理智柱状图 ----
    from datetime import timedelta as _td
    # 按 ISO 周分组，记录每周起止日期
    weekly_sanity = defaultdict(int)
    weekly_start = {}
    weekly_end = {}
    for d in dates:
        dt = datetime.strptime(d, '%Y-%m-%d')
        iso = dt.isocalendar()
        week_key = f"{iso[0]}-W{iso[1]:02d}"
        weekly_sanity[week_key] += daily_data[d]['sanity']
        week_start = dt - _td(days=dt.weekday())
        week_end = week_start + _td(days=6)
        if week_key not in weekly_start:
            weekly_start[week_key] = week_start
            weekly_end[week_key] = week_end
    weeks_sorted = sorted(weekly_sanity.keys())
    max_weekly = max(weekly_sanity.values()) if weekly_sanity else 1

    if weeks_sorted:
        H.append('<section>')
        H.append('  <div class="card">')
        H.append('    <div class="card-title"><strong>周度理智消耗</strong></div>')
        H.append('    <div class="bar-chart">')
        for wk in weeks_sorted:
            v = weekly_sanity[wk]
            h = (v / max_weekly * 100) if max_weekly else 0
            ws = weekly_start[wk]
            we = weekly_end[wk]
            label = f"{ws.month}/{ws.day}~{we.month}/{we.day}"
            H.append('      <div class="bar-col">')
            H.append(f'        <div class="bar-val">{v}</div>')
            H.append(f'        <div class="bar" style="height:{h:.0f}%" title="{label}: {v} 理智"></div>')
            H.append(f'        <div class="bar-label">{label}</div>')
            H.append('      </div>')
        H.append('    </div>')
        H.append('  </div>')
        H.append('</section>')

    # ---- 材料仓库 ----
    if top_items:
        H.append('<section>')
        H.append('  <div class="card">')
        H.append(f'    <strong>材料仓库（{len(top_items)} 种）</strong>')
        H.append('    <div class="items-grid">')
        for name, qty in top_items[:30]:
            H.append('      <div class="item-cell">')
            H.append(f'        <div class="item-icon">{item_img_tag(name, 40)}</div>')
            H.append(f'        <div class="item-name">{esc(name)}</div>')
            H.append(f'        <div class="item-qty">{fmt_qty(qty)}</div>')
            H.append('      </div>')
        H.append('    </div>')
        H.append('  </div>')
        H.append('</section>')

    # ---- 理智消耗关卡（按战斗次数排名，附带估算理智）----
    stage_battles = defaultdict(int)
    total_battles_all = 0
    total_sanity_all = 0
    for d in daily_data.values():
        total_sanity_all += d['sanity']
        for stage, info in d['drops'].items():
            stage_battles[stage] += info['times']
            total_battles_all += info['times']
    if stage_battles:
        sorted_stages = sorted(stage_battles.items(), key=lambda x: -x[1])[:15]
        max_sb = sorted_stages[0][1] if sorted_stages else 1
        H.append('<section>')
        H.append('  <div class="card">')
        H.append('    <div class="card-title"><strong>理智消耗关卡</strong></div>')
        for stage, sb in sorted_stages:
            pct = sb / max_sb * 100 if max_sb else 0
            est_sanity = int(total_sanity_all * sb / total_battles_all) if total_battles_all else 0
            H.append('    <div class="rank-row">')
            H.append(f'      <div class="rank-name">{esc(stage)}</div>')
            H.append(f'      <div class="rank-bar-wrap"><div class="rank-bar" style="width:{pct:.1f}%"></div></div>')
            H.append(f'      <div class="rank-num">{sb} 次 · {est_sanity} 理智</div>')
            H.append('    </div>')
        H.append('  </div>')
        H.append('</section>')

    # ---- 肉鸽深度分析 ----
    if all_rogue:
        H.append('<section>')
        H.append('  <div class="card">')
        H.append('    <div class="card-title"><strong>肉鸽深度分析</strong></div>')
        H.append('    <div class="rogue-hero">')
        H.append(f'      <div class="rogue-hero-item"><div class="rogue-hero-num win">{len(rogue_wins)}</div><div class="rogue-hero-label">通关</div></div>')
        H.append(f'      <div class="rogue-hero-item"><div class="rogue-hero-num lose">{len(rogue_loses)}</div><div class="rogue-hero-label">失败</div></div>')
        H.append(f'      <div class="rogue-hero-item"><div class="rogue-hero-num rate">{rogue_win_rate:.0f}%</div><div class="rogue-hero-label">胜率</div></div>')
        H.append(f'      <div class="rogue-hero-item"><div class="rogue-hero-num">{avg_floors_all:.1f}</div><div class="rogue-hero-label">平均层数</div></div>')
        H.append(f'      <div class="rogue-hero-item"><div class="rogue-hero-num">{avg_score:.0f}</div><div class="rogue-hero-label">通关平均分</div></div>')
        H.append('    </div>')
        H.append('    <table style="margin-top:12px"><thead><tr><th>难度</th><th class="num">次数</th><th class="num">通关</th><th class="num">失败</th><th class="num">胜率</th><th class="num">平均层数</th><th class="num">平均分</th></tr></thead><tbody>')
        for level in sorted(by_level.keys(), key=natural_key):
            runs = by_level[level]
            wins = [r for r in runs if r.get('result') == '✓']
            loses = [r for r in runs if r.get('result') == '✗']
            rate = len(wins) / len(runs) * 100 if runs else 0
            avg_f = sum(r.get('floors', 0) for r in runs) / len(runs) if runs else 0
            avg_s = sum(r.get('score', 0) for r in wins) / len(wins) if wins else 0
            rate_color = 'var(--green)' if rate >= 50 else ('var(--yellow)' if rate >= 25 else 'var(--red)')
            H.append(
                f'      <tr><td><strong>{esc(level)}</strong></td>'
                f'<td class="num">{len(runs)}</td>'
                f'<td class="num" style="color:var(--green)">{len(wins)}</td>'
                f'<td class="num" style="color:var(--red)">{len(loses)}</td>'
                f'<td class="num" style="color:{rate_color}">{rate:.0f}%</td>'
                f'<td class="num">{avg_f:.1f}</td>'
                f'<td class="num">{avg_s:.0f}</td></tr>'
            )
        H.append('    </tbody></table>')
        if recent_rogue:
            H.append('    <h3 style="font-size:11px;margin:12px 0 6px;color:var(--text-muted)">最近 10 次</h3>')
            H.append('    <div class="timeline">')
            for r in recent_rogue:
                ts = r.get('ts', '')[:16]
                result = r.get('result', '?')
                level = r.get('level', '?')
                floors = r.get('floors', 0)
                steps = r.get('steps', 0)
                score = r.get('score', 0)
                cls = 'win' if result == '✓' else 'lose'
                score_str = f' · 得分 {score}' if score > 0 else ''
                H.append(
                    f'      <div class="tl-item {cls}">'
                    f'<span class="tl-time">{ts[5:]}</span>'
                    f'<strong>{result} {esc(level)}</strong>'
                    f' · {floors}层/{steps}步{score_str}</div>'
                )
            H.append('    </div>')
        H.append('  </div>')
        H.append('</section>')

    # ---- 每日详情 ----
    if dates:
        H.append('<section>')
        H.append('  <strong style="font-size:16px">每日详情</strong>')
        for idx, date in enumerate(reversed(dates)):
            d = daily_data[date]
            try:
                weekday = WEEKDAY_CN[datetime.strptime(date, '%Y-%m-%d').weekday()]
            except ValueError:
                weekday = '?'
            battles = sum(info['times'] for info in d['drops'].values())
            open_attr = ' open' if idx == 0 else ''
            H.append(f'  <details class="day-card" style="margin-top:10px"{open_attr}>')
            H.append('    <summary>')
            H.append(f'      <span>{date} ({weekday})</span>')
            if d['sanity']:
                H.append(f'      <span class="badge sanity">理智 {d["sanity"]}</span>')
            if battles:
                H.append(f'      <span class="badge battle">{battles} 次战斗</span>')
            if d['recruit']:
                H.append(f'      <span class="badge recruit">招募 {d["recruit"]}</span>')
            if d['rogue']:
                wins_today = sum(1 for r in d['rogue'] if r.get('result') == '✓')
                H.append(f'      <span class="badge rogue">肉鸽 {wins_today}/{len(d["rogue"])}</span>')
            H.append('    </summary>')
            H.append('    <div class="day-content">')

            if d['drops']:
                H.append('      <h3>材料掉落</h3>')
                for stage in sorted(d['drops'].keys(), key=natural_key):
                    info = d['drops'][stage]
                    if info['times'] == 0 and not info['items']:
                        continue
                    pills = []
                    for name, q in sorted(info['items'].items(), key=lambda kv: -(kv[1]['base'] + kv[1]['extra'])):
                        total_q = q['base'] + q['extra']
                        if total_q <= 0:
                            continue
                        icon = item_img_tag(name, 20)
                        pills.append(f'<span class="pill" style="display:inline-flex;align-items:center;gap:4px">{icon}{esc(name)}<span class="qty">{fmt_qty(total_q)}</span></span>')
                    pills_html = ''.join(pills) if pills else '<span class="empty">—</span>'
                    H.append(f'      <div style="margin:4px 0;font-size:13px"><strong>{esc(stage)}</strong> <span style="color:var(--text-muted)">x{info["times"]}</span> · {pills_html}</div>')

            if d['rogue']:
                H.append('      <h3 style="margin-top:10px">肉鸽记录</h3>')
                for r in d['rogue']:
                    rc = 'var(--green)' if r.get('result') == '✓' else 'var(--red)'
                    score_str = f' · 得分 {r.get("score",0)}' if r.get('score',0) else ''
                    H.append(f'      <div style="font-size:12px;color:var(--text-muted);margin:2px 0"><span style="color:{rc};font-weight:600">{esc(r.get("result",""))}</span> {esc(r.get("level",""))} · {r.get("floors",0)}层{r.get("steps",0)}步{score_str}</div>')

            if not d['drops'] and not d['rogue']:
                H.append('      <div class="empty">今日无战斗 / 肉鸽记录</div>')

            H.append('    </div>')
            H.append('  </details>')
        H.append('</section>')

    H.append('</div></body></html>')

    # 注入收集到的材料图片 CSS（base64 只写一次）
    if _CSS_IMAGES:
        extra_css = '\n'.join(_CSS_IMAGES)
        html_content = '\n'.join(H).replace('</style>', extra_css + '\n</style>')
    else:
        html_content = '\n'.join(H)
    REPORT_HTML_CACHE['content'] = html_content
    log("✅ 报告已生成")


# ---------- GUI (本地 Web UI) ----------
def run_gui():
    import threading, json as _json
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import urllib.parse

    state_data = {'log_path': '', 'running': False, 'progress': 0, 'msg': '', 'done': False, 'error': ''}

    state_data['log_path'] = load_config() or ''

    HTML_UI = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>MAA 作战日报</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0f0f14;color:#e8e8f0;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh}
.box{background:#1a1a26;border:1px solid #252535;border-radius:12px;padding:32px;width:480px}
h1{font-size:20px;color:#a78bfa;margin-bottom:4px}
.sub{color:#707088;font-size:12px;margin-bottom:24px}
label{font-size:12px;color:#707088;display:block;margin-bottom:6px}
.row{display:flex;gap:8px;margin-bottom:16px}
input{flex:1;background:#12121a;border:1px solid #252535;border-radius:8px;padding:10px 12px;color:#e8e8f0;font-size:12px;outline:none}
input:focus{border-color:#8b5cf6}
button{background:#8b5cf6;color:#fff;border:none;border-radius:8px;padding:10px 20px;font-size:14px;font-weight:600;cursor:pointer;width:100%;margin-top:8px}
button:disabled{opacity:.5;cursor:default}
button.secondary{background:#252535;font-size:12px;padding:10px 14px;width:auto}
button.exit{background:#2a1a2a;color:#e07070;margin-top:12px;border:1px solid #4a2030}
.progress{height:6px;background:#12121a;border-radius:3px;margin:16px 0 8px;overflow:hidden}
.bar{height:100%;background:#8b5cf6;border-radius:3px;transition:width .3s;width:0%}
.status{font-size:11px;color:#707088;min-height:16px}
.log{background:#12121a;border:1px solid #252535;border-radius:8px;padding:10px;font-family:Consolas,monospace;font-size:10px;color:#8888a0;max-height:160px;overflow-y:auto;margin-top:12px;white-space:pre-wrap;word-break:break-all}
.link{display:none;margin-top:12px;text-decoration:none}
.link-btn{display:block;background:#8b5cf6;color:#fff;text-align:center;border-radius:8px;padding:12px;font-size:14px;font-weight:600;text-decoration:none;cursor:pointer}
.link-btn:hover{background:#7c3aed}
</style></head><body><div class="box">
<h1>MAA 作战日报</h1>
<div class="sub">解析 MAA 日志，生成可视化作战报告</div>
<label>MAA 日志路径 (gui.log)</label>
<div class="row">
<input id="path" value="__PATH__">
<button class="secondary" onclick="document.getElementById('file').click()">浏览</button>
<input type="file" id="file" style="display:none" onchange="document.getElementById('path').value=this.files[0].path">
</div>
<button id="genBtn" onclick="generate()">生成日报</button>
<div class="progress"><div class="bar" id="bar"></div></div>
<div class="status" id="status">准备就绪</div>
<div class="log" id="log"></div>
<a class="link" id="link" href="#" target="_blank"><span class="link-btn">打开报告</span></a>
<button class="exit" onclick="exitApp()">退出程序</button>
</div>
<script>
var events = new EventSource('/events');
events.onmessage = function(e){
  var d = JSON.parse(e.data);
  document.getElementById('bar').style.width = d.progress + '%';
  document.getElementById('status').textContent = d.msg;
  if (d.log) document.getElementById('log').textContent += d.log + '\\n';
  if (d.done) {
    document.getElementById('genBtn').disabled = false;
    document.getElementById('genBtn').textContent = '重新生成';
    var link = document.getElementById('link');
    link.style.display = 'block';
    link.href = '/report?ts=' + Date.now();
  }
  if (d.error) {
    document.getElementById('status').textContent = '错误: ' + d.error;
    document.getElementById('genBtn').disabled = false;
  }
};
function generate(){
  var p = document.getElementById('path').value;
  if (!p) { alert('请选择 gui.log 路径'); return; }
  document.getElementById('genBtn').disabled = true;
  document.getElementById('genBtn').textContent = '生成中...';
  document.getElementById('log').textContent = '';
  fetch('/generate?path=' + encodeURIComponent(p)).then(r=>r.json());
}
function exitApp(){
  fetch('/shutdown').then(()=>{
    document.body.innerHTML = '<p style="text-align:center;color:#707088">程序已退出，可以关闭此页面</p>';
  });
}
// 关闭页面时自动退出
window.addEventListener('beforeunload', function(){
  if (!state_data_generating) navigator.sendBeacon('/shutdown');
});
</script></body></html>"""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == '/':
                html = HTML_UI.replace('__PATH__', state_data['log_path'])
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
            elif parsed.path == '/events':
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                import time as _t
                try:
                    while True:
                        evt = {'progress': state_data['progress'], 'msg': state_data['msg'],
                               'log': state_data.get('new_log', ''), 'done': state_data['done'],
                               'error': state_data['error']}
                        state_data['new_log'] = ''
                        self.wfile.write(f'data: {_json.dumps(evt)}\n\n'.encode())
                        self.wfile.flush()
                        _t.sleep(0.3)
                except Exception:
                    pass
            elif parsed.path == '/generate':
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                path = qs.get('path', [''])[0]
                state_data['log_path'] = path
                state_data['running'] = True
                state_data['done'] = False
                state_data['error'] = ''
                state_data['progress'] = 0
                state_data['msg'] = '开始...'
                state_data['new_log'] = ''
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            elif parsed.path == '/shutdown':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
                import threading, time
                def _shutdown():
                    time.sleep(0.3)
                    os._exit(0)
                threading.Thread(target=_shutdown, daemon=True).start()
            elif parsed.path == '/report':
                content = REPORT_HTML_CACHE.get('content', '')
                if content:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(content.encode('utf-8'))
                else:
                    self.send_response(404)
                    self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            self.send_response(404)
            self.end_headers()

    def run_generate(path):
        global LOG_PATH
        LOG_PATH = path
        save_config(path)
        try:
            state_data['new_log'] = f'日志: {path}\n'
            state_data['progress'] = 10
            state_data['msg'] = '加载历史库...'
            migrate_legacy_state()
            state = HistoryState(STATE_PATH)
            state_data['new_log'] = f'历史库: {len(state.events)} 条事件\n'
            state_data['progress'] = 30
            state_data['msg'] = '解析日志...'
            if not parse_all_logs(state):
                state_data['error'] = '解析失败'
                state_data['progress'] = 100
                return
            state.save()
            state_data['progress'] = 60
            state_data['msg'] = '聚合数据...'
            daily = aggregate_events(state)
            state_data['progress'] = 85
            state_data['msg'] = '渲染 HTML...'
            generate_html(daily, state)
            state_data['progress'] = 100
            state_data['msg'] = '完成'
            state_data['done'] = True
        except Exception as e:
            import traceback
            state_data['error'] = str(e)
            state_data['new_log'] = traceback.format_exc()

    def wait_and_generate():
        while True:
            if state_data['running'] and not state_data.get('_generating'):
                state_data['_generating'] = True
                run_generate(state_data['log_path'])
                state_data['running'] = False
                state_data['_generating'] = False
            import time
            time.sleep(0.5)

    threading.Thread(target=wait_and_generate, daemon=True).start()

    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(('127.0.0.1', 18923), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # 用 pywebview 内嵌窗口，不打开外部浏览器
    try:
        import webview
        window = webview.create_window(
            'MAA 作战日报',
            'http://127.0.0.1:18923',
            width=520, height=680,
            resizable=False,
        )
        webview.start()
        # 窗口关闭后直接退出
        os._exit(0)
    except ImportError:
        import webbrowser
        webbrowser.open('http://127.0.0.1:18923')
        server.serve_forever()


if __name__ == '__main__':
    run_gui()
