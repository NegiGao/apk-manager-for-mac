"""界面检查（无头 Chromium + 假 adb）：版本 / 制作者 / GitHub 地址，以及安装队列每一行的「单独安装」「卸载」按钮。

用法：python3 tests/ui_check.py [截图输出目录]
"""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Inst, APKS, CODE  # noqa: E402

RESULTS = []
USB = "FAKE1234567890"


def check(cond, msg):
    RESULTS.append(bool(cond))
    print(("   ✓ " if cond else "   ✗ ") + msg, flush=True)


def main():
    from playwright.sync_api import sync_playwright
    out = sys.argv[1] if len(sys.argv) > 1 else None
    vns = {}
    exec(open(os.path.join(CODE, "core", "version.py")).read(), vns)
    I = Inst("ui", {"APKMGR_DISCOVERY_INTERVAL": "1"}, {"lang": "zh"})
    try:
        I.wait(lambda: I.sup()["devicesAt"] and I.sup().get("selected") == USB, what="设备")
        I.preinstall("termux", "com.termux")
        for k in ("termux", "newpipe", "seal"):
            I.post("/api/import", {"path": APKS[k]})
        I.post("/api/mark", {"serial": USB})
        print("\n[界面] 版本 / 制作者 / 每行按钮")
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1400, "height": 900}, locale="zh-CN")
            dialogs = []

            def on_dialog(d):
                dialogs.append(d.message)
                d.accept()
            pg.on("dialog", on_dialog)
            pg.goto(I.B + "/")
            pg.wait_for_selector("#list .row .in1")
            pg.wait_for_function("document.querySelectorAll('#list .row').length === 3")
            time.sleep(1)
            badge = pg.inner_text("#appVerBadge")
            line = pg.inner_text("#aboutLine")
            href = pg.get_attribute("#aboutLine a", "href")
            check(badge == "v" + vns["VERSION"], "顶部显示版本（%s）" % badge)
            check("NegiGao" in line and href == vns["HOMEPAGE"], "顶部显示制作者和 GitHub 地址（%s｜%s）" % (line, href))
            check(("v" + vns["VERSION"]) in pg.title(), "窗口标题带版本（%s）" % pg.title())
            rows = pg.query_selector_all("#list .row")
            info = []
            for r in rows:
                name = r.query_selector(".name").inner_text()
                in1 = r.query_selector(".row-actions .in1")
                un1 = r.query_selector(".row-actions .un1")
                st = r.query_selector(".status").bounding_box()
                act = r.query_selector(".row-actions").bounding_box()
                info.append((name, in1.inner_text() if in1 else None, bool(un1), act["x"] + act["width"] <= st["x"] + 1))
            check(all(x[1] == "单独安装" for x in info), "每一行都有「单独安装」（%s）" % [x[1] for x in info])
            check([x[0] for x in info if x[2]] == ["Termux"], "「卸载」只出现在设备上已安装的那一项（%s）" % [x[0] for x in info if x[2]])
            check(all(x[3] for x in info), "按钮在状态文字的左边（红框位置）")
            if out:
                os.makedirs(out, exist_ok=True)
                pg.screenshot(path=os.path.join(out, "queue-row-buttons.png"))

            t = time.time()
            seal = [r for r in rows if r.query_selector(".name").inner_text() == "Seal"][0]
            seal.query_selector(".in1").click()
            I.wait(lambda: any(e["type"] == "install_done" for e in I.events), timeout=30, what="单独安装完成")
            inst = [a for ts, a in I.adb_calls(t) if re.search(r" install ", a)]
            check(len(inst) == 1 and inst[0].endswith("seal.apk"), "点「单独安装」：只装 Seal 一个（%s）" % [a.split("/")[-1] for a in inst])

            if pg.is_visible("#modal"):                     # 安装完成后程序会弹出结果汇总，先关掉
                pg.click("#modalOk")
            pg.wait_for_function("[...document.querySelectorAll('#list .row')].some(r => r.querySelector('.name').innerText==='Termux' && r.querySelector('.un1') && !r.querySelector('.un1').disabled)")
            t = time.time()
            I.events.clear()
            row = [r for r in pg.query_selector_all("#list .row") if r.query_selector(".name").inner_text() == "Termux"][0]
            row.query_selector(".un1").click()
            I.wait(lambda: any(e["type"] == "uninstall_done" for e in I.events), timeout=30, what="卸载完成")
            un = [a for ts, a in I.adb_calls(t) if " uninstall " in a]
            check(dialogs and "Termux" in dialogs[-1] and "设备：" in dialogs[-1],
                  "卸载前确认框写明应用和设备（%s）" % (dialogs[-1].replace("\n", " ")[:80] if dialogs else "无"))
            check(len(un) == 1 and un[0].endswith("com.termux"), "确认后只卸载 Termux（%s）" % un)

            if pg.is_visible("#modal"):
                pg.click("#modalOk")
            pg.click('[data-tab="settings"]')
            box = pg.inner_text("#aboutBox")
            check("NegiGao" in box and vns["VERSION"] in box and "github.com/NegiGao/apk-manager-for-mac" in box and "MIT" in box,
                  "「设置 → 关于」显示版本、制作者、GitHub、许可协议")
            if out:
                card = pg.locator("#aboutBox").locator("xpath=..")
                card.scroll_into_view_if_needed()
                card.screenshot(path=os.path.join(out, "settings-about.png"))
            b.close()
    finally:
        I.close()
    ok = sum(RESULTS)
    print("\n===== 界面检查 %d / %d 项通过 =====" % (ok, len(RESULTS)))
    return 0 if RESULTS and ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
