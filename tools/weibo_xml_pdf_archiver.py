# -*- coding: utf-8 -*-
# 山西大学微博归档脚本：
# 1. 运行微博爬虫（按当前 config 配置，默认 PLATFORM=wb 且 CRAWLER_TYPE=creator）
# 2. 读取爬取后的 JSON 内容文件
# 3. 过滤出配置时间范围内、指定账号（山西大学）的微博
# 4. 每条微博生成一个 XML（格式同你提供的示例）和一个 PDF

import asyncio
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

# 确保可以从项目根目录导入 config / media_platform 等包
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 输出目录：桌面下的 weibo_sxu_{日期} 文件夹
DESKTOP_DIR = os.path.join(os.path.expanduser("~"), "Desktop")


def _weibo_output_base_dir() -> str:
    return os.path.join(DESKTOP_DIR, "weibo_sxu_202601")


def get_default_xml_output_dir() -> str:
    return os.path.join(_weibo_output_base_dir(), "output_xml_sxu_202601")


def get_default_pdf_output_dir() -> str:
    return os.path.join(_weibo_output_base_dir(), "output_pdf_sxu_202601")


import config
from media_platform.weibo import WeiboCrawler
from tools import utils

import xml.etree.ElementTree as ET

# Playwright：用于通过 Chrome 打开详情页并保存为 PDF
try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

logger = utils.logger


class WeiboArchiver:
    """
    将微博 JSON 内容转换为：
    1. 归档 XML（你给出的格式）
    2. 对应的 PDF 文档
    """

    def __init__(
        self,
        xml_output_dir: str = None,
        pdf_output_dir: str = None,
    ) -> None:
        self.xml_output_dir = xml_output_dir or get_default_xml_output_dir()
        self.pdf_output_dir = pdf_output_dir or get_default_pdf_output_dir()

        os.makedirs(self.xml_output_dir, exist_ok=True)
        os.makedirs(self.pdf_output_dir, exist_ok=True)

    @staticmethod
    def make_safe_filename(title: str) -> str:
        """将标题转为安全的文件名"""
        if not title:
            return "weibo_item"
        filename = re.sub(r"[\\/:*?\"<>|]", "_", title)
        filename = filename.strip(" .")
        return filename[:80] or "weibo_item"

    @staticmethod
    def build_news_data(item: Dict[str, Any]) -> Dict[str, str]:
        """
        从 JSON 中的一条微博记录构造 XML / PDF 需要的元数据结构。

        预期字段（来自 store/weibo/__init__.py 的 save_content_item）：
            - content
            - create_date_time
            - note_url
            - nickname
        """
        content = (item.get("content") or "").strip()
        create_dt = str(item.get("create_date_time") or "")
        url = item.get("note_url") or ""
        nickname = item.get("nickname") or "山西大学微博"

        # 标题：取正文前 30 个字符
        if content:
            title = content[:30] + ("…" if len(content) > 30 else "")
        else:
            title = "无标题微博"

        return {
            "title": title,
            "url": url,
            "publish_time": create_dt,
            "source": nickname,
            "editor": nickname,
            "content": content,
        }

    def save_as_xml(self, news_data: Dict[str, str]) -> Optional[str]:
        """
        将元数据保存为 XML。
        XML 结构严格参考用户提供的示例：

        <归档事项基本信息>
            <正题名>...</正题名>
            <副题名>...</副题名>
            <时间>...</时间>
            <单位>...</单位>
            <归档部门>...</归档部门>
            <责任者>...</责任者>
        </归档事项基本信息>
        """
        try:
            filename = self.make_safe_filename(news_data["title"])
            xml_path = os.path.join(self.xml_output_dir, f"{filename}.xml")

            root = ET.Element("归档事项基本信息")
            ET.SubElement(root, "正题名").text = news_data["title"]
            ET.SubElement(root, "副题名").text = news_data["url"]
            ET.SubElement(root, "时间").text = news_data["publish_time"]
            ET.SubElement(root, "单位").text = news_data["source"]
            ET.SubElement(root, "归档部门").text = news_data["source"]
            ET.SubElement(root, "责任者").text = news_data["editor"]

            tree = ET.ElementTree(root)
            tree.write(xml_path, encoding="utf-8", xml_declaration=True)

            logger.info(f"[WeiboArchiver] XML 保存成功: {xml_path}")
            return xml_path
        except Exception as e:
            logger.error(f"[WeiboArchiver] 保存 XML 失败: {e}")
            return None

    async def save_as_pdf_via_chrome(
        self, page: Any, news_data: Dict[str, str], wait_after_load_ms: int = 2000
    ) -> Optional[str]:
        """
        通过 Chrome 打开微博详情页（副题名 URL）并打印为 PDF。
        使用 Playwright 的 page.pdf()，得到与浏览器界面一致的 PDF。
        """
        if not HAS_PLAYWRIGHT:
            return None
        url = (news_data.get("url") or "").strip()
        if not url or not url.startswith("http"):
            logger.warning("[WeiboArchiver] 副题名 URL 为空或无效，跳过浏览器 PDF")
            return None
        try:
            filename = self.make_safe_filename(news_data["title"])
            pdf_path = os.path.join(self.pdf_output_dir, f"{filename}.pdf")

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(wait_after_load_ms)

            await page.pdf(
                path=pdf_path,
                format="A4",
                print_background=True,
                margin={"top": "10mm", "right": "10mm", "bottom": "10mm", "left": "10mm"},
            )
            logger.info(f"[WeiboArchiver] 浏览器 PDF 保存成功: {pdf_path}")
            return pdf_path
        except Exception as e:
            logger.error(f"[WeiboArchiver] 通过浏览器保存 PDF 失败: {e}")
            return None

def _load_news_data_from_xml_dir(xml_dir: str) -> List[Dict[str, str]]:
    """
    从已生成的 XML 目录读取每条记录的 正题名、副题名（detail URL）等，用于仅重跑 PDF。
    返回与 build_news_data 结构兼容的列表，至少包含 title、url。
    """
    if not os.path.isdir(xml_dir):
        return []
    result: List[Dict[str, str]] = []
    for name in os.listdir(xml_dir):
        if not name.endswith(".xml"):
            continue
        path = os.path.join(xml_dir, name)
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            title = (root.findtext("正题名") or "").strip() or "无标题"
            url = (root.findtext("副题名") or "").strip()
            time_ = (root.findtext("时间") or "").strip()
            source = (root.findtext("单位") or "").strip()
            result.append({
                "title": title,
                "url": url,
                "publish_time": time_,
                "source": source or "山西大学微博",
                "editor": (root.findtext("责任者") or "").strip() or source,
                "content": "",
            })
        except Exception as e:
            logger.warning(f"[WeiboArchiver] 解析 XML 失败 {path}: {e}")
    return result


def _parse_time_range() -> Optional[tuple[datetime, datetime]]:
    """
    从 config.weibo_config 中读取起止时间字符串，并解析为 datetime。
    预期格式：YYYY-MM-DD HH:MM:SS
    """
    start_str = getattr(config, "WEIBO_CRAWL_START_TIME", "")
    end_str = getattr(config, "WEIBO_CRAWL_END_TIME", "")
    if not start_str or not end_str:
        logger.error("[WeiboArchiver] WEIBO_CRAWL_START_TIME / WEIBO_CRAWL_END_TIME 未配置")
        return None

    try:
        start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S")
        return start_dt, end_dt
    except Exception as e:
        logger.error(f"[WeiboArchiver] 解析时间范围失败: {e}")
        return None


def _parse_create_datetime(create_dt_str: str) -> Optional[datetime]:
    """
    解析 JSON 中的 create_date_time 字段。
    该字段由 utils.rfc2822_to_china_datetime 生成，形如：2026-01-03 10:20:30+08:00
    """
    if not create_dt_str:
        return None
    try:
        # 优先按 ISO 格式解析
        return datetime.fromisoformat(create_dt_str)
    except Exception:
        # 兜底尝试不含时区的格式
        try:
            return datetime.strptime(create_dt_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            logger.warning(f"[WeiboArchiver] 无法解析 create_date_time: {create_dt_str}")
            return None


def _load_weibo_json_contents() -> List[Dict[str, Any]]:
    """
    读取 data/weibo/json/creator_contents_*.json 中的所有微博内容记录。
    """
    base_pattern = os.path.join("data", "weibo", "json", "creator_contents_*.json")
    files = sorted(glob.glob(base_pattern))
    if not files:
        logger.warning("[WeiboArchiver] 未在 data/weibo/json/creator_contents_*.json 下找到任何内容 JSON 文件，请先运行 main.py 完成爬取。")
        return []

    all_items: List[Dict[str, Any]] = []
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    continue
                data = json.loads(content)
                if isinstance(data, list):
                    all_items.extend(data)
                elif isinstance(data, dict):
                    all_items.append(data)
            logger.info(f"[WeiboArchiver] 已加载 JSON 文件: {fp}, 条数: {len(all_items)}")
        except Exception as e:
            logger.error(f"[WeiboArchiver] 读取 JSON 文件失败 {fp}: {e}")

    return all_items


def _filter_items_for_sxu(
    items: List[Dict[str, Any]],
    time_range: tuple[datetime, datetime],
) -> List[Dict[str, Any]]:
    """
    过滤出：
      1. 时间在配置范围内（WEIBO_CRAWL_START_TIME ~ WEIBO_CRAWL_END_TIME）
      2. 账号为山西大学（根据 user_id 或 nickname）
    """
    start_dt, end_dt = time_range

    # 从配置里取创作者 ID（你可以在 config/weibo_config.py 中把山西大学 UID 填进去）
    creator_ids = getattr(config, "WEIBO_CREATOR_ID_LIST", []) or []
    creator_ids_str = {str(uid).strip() for uid in creator_ids if str(uid).strip()}

    result: List[Dict[str, Any]] = []
    for item in items:
        nickname = (item.get("nickname") or "").strip()
        user_id = str(item.get("user_id") or "").strip()
        create_dt_str = str(item.get("create_date_time") or "")
        create_dt = _parse_create_datetime(create_dt_str)
        if not create_dt:
            continue
        # 配置的 start_dt/end_dt 为 naive，create_dt 可能带时区，统一转为 naive 再比较
        if create_dt.tzinfo is not None:
            create_dt = create_dt.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)

        # 时间过滤
        if not (start_dt <= create_dt <= end_dt):
            continue

        # 账号过滤：优先用 user_id，其次用昵称（“山西大学”）
        if creator_ids_str:
            if user_id not in creator_ids_str:
                continue
        else:
            if nickname != "山西大学":
                continue

        result.append(item)

    logger.info(f"[WeiboArchiver] 过滤后符合条件的微博数量: {len(result)}")
    return result


async def crawl_weibo_if_needed() -> None:
    """
    如果本地还没有 JSON 内容文件，可以先调用微博爬虫完成一次爬取。
    """
    contents = _load_weibo_json_contents()
    if contents:
        # 已经有数据，就不重复爬
        return

    logger.info("[WeiboArchiver] 没有找到本地微博 JSON 数据，将先运行一次微博爬虫...")
    crawler = WeiboCrawler()
    await crawler.start()
    logger.info("[WeiboArchiver] 微博爬虫运行完成。")


async def _run_pdf_from_xml_only(xml_dir: str, pdf_dir: str) -> None:
    """
    仅从已有 XML 目录读取每条记录的副题名（detail URL），用 Chrome 打开并保存为 PDF。
    适用于已生成 XML、只需重跑 PDF 的场景。
    """
    items = _load_news_data_from_xml_dir(xml_dir)
    if not items:
        logger.warning("[WeiboArchiver] 未在 XML 目录中找到任何记录，请先运行完整归档生成 XML。")
        return
    if not HAS_PLAYWRIGHT:
        logger.error("[WeiboArchiver] 需要安装 playwright 才能通过浏览器生成 PDF。")
        return
    archiver = WeiboArchiver(xml_output_dir=xml_dir, pdf_output_dir=pdf_dir)
    logger.info(f"[WeiboArchiver] 从 XML 读取 {len(items)} 条，使用 Chrome 按副题名 URL 生成 PDF。")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=getattr(config, "CDP_HEADLESS", False))
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()
        try:
            for news_data in items:
                await archiver.save_as_pdf_via_chrome(page, news_data)
        finally:
            await browser.close()
    logger.info("[WeiboArchiver] 仅 PDF 生成完成。")


async def main() -> None:
    """
    总入口：
    1. 如有需要先爬取微博数据
    2. 从 JSON 读取微博内容
    3. 过滤出 2026 年 1 月（或配置时间段内）的山西大学微博
    4. 批量生成 XML + PDF（PDF 可通过 Chrome 打开副题名详情页打印）
    若传入 --pdf-from-xml，则仅从已有 XML 目录按副题名 URL 批量生成 PDF。
    """
    # 仅从已有 XML 生成 PDF（副题名 = detail URL）
    if len(sys.argv) > 1 and sys.argv[1].strip() == "--pdf-from-xml":
        xml_dir = os.environ.get("WEIBO_XML_DIR") or get_default_xml_output_dir()
        pdf_dir = os.environ.get("WEIBO_PDF_DIR") or get_default_pdf_output_dir()
        await _run_pdf_from_xml_only(xml_dir, pdf_dir)
        return

    time_range = _parse_time_range()
    if not time_range:
        return

    # 如无数据则尝试先爬一次
    await crawl_weibo_if_needed()

    # 再次读取（防止刚刚爬完）
    items = _load_weibo_json_contents()
    if not items:
        logger.error("[WeiboArchiver] 仍然没有微博数据，无法进行归档。")
        return

    sxu_items = _filter_items_for_sxu(items, time_range)
    if not sxu_items:
        logger.warning("[WeiboArchiver] 没有找到符合条件的山西大学微博数据。")
        return

    archiver = WeiboArchiver()
    use_browser_pdf = getattr(config, "WEIBO_PDF_VIA_BROWSER", False) and HAS_PLAYWRIGHT

    if use_browser_pdf:
        logger.info("[WeiboArchiver] 使用 Chrome 打开每条微博详情页（副题名 URL）并保存为 PDF。")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=getattr(config, "CDP_HEADLESS", False))
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = await context.new_page()
            try:
                for item in sxu_items:
                    news_data = archiver.build_news_data(item)
                    archiver.save_as_xml(news_data)
                    await archiver.save_as_pdf_via_chrome(page, news_data)
            finally:
                await browser.close()
    else:
        logger.info("[WeiboArchiver] 未启用浏览器 PDF 或未安装 playwright，每条微博仅生成 XML。")
        for item in sxu_items:
            news_data = archiver.build_news_data(item)
            archiver.save_as_xml(news_data)

    logger.info("[WeiboArchiver] 所有符合条件的微博已生成 XML 与 PDF。")


if __name__ == "__main__":
    asyncio.run(main())

