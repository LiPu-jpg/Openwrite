import asyncio, json, os
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = "/Users/jiaoziang/openjiu/demo-works"
NOVEL = "demo_novel"

async def call(c, name, **kw):
    r = await c.call_tool(name, kw)
    try:
        return json.loads(r.content[0].text)
    except Exception:
        return {"_raw": r.content[0].text[:500]}

async def main():
    env = dict(os.environ)
    env["OPENWRITE_CORE"] = "/Users/jiaoziang/openjiu/Openwrite-native-core"
    t = StdioTransport(command="/Users/jiaoziang/openjiu/.venv-swarm/bin/python",
                       args=["/Users/jiaoziang/openjiu/openwrite-mcp/server.py"], env=env)
    async with Client(t) as c:
        # 1. 收稿门初始状态
        st = await call(c, "manuscript_status", project_root=ROOT, novel_id=NOVEL)
        chaps = st.get("chapters", [])
        print("1. manuscript_status ok:", st.get("ok"), "| chapters:", [(x.get("chapter_id"), x.get("status")) for x in chaps])

        # 2. 蜂群产章写入（用真实冒烟产出的正文）
        smoke = json.load(open("/Users/jiaoziang/openjiu/openwrite-novel-swarm/tests/smoke_real_output.json"))
        text = smoke["result"]["chapter_text"]
        sv = await call(c, "save_external_chapter", project_root=ROOT, novel_id=NOVEL,
                        chapter_id="ch_001", title="第一章 多出来的客人", content=text)
        print("2. save_external_chapter ok:", sv.get("ok"), "| chars:", sv.get("chars"))

        # 3. 写入后状态
        st2 = await call(c, "manuscript_status", project_root=ROOT, novel_id=NOVEL)
        print("3. after save:", [(x.get("chapter_id"), x.get("status")) for x in st2.get("chapters", [])])

        # 4. 两阶段门：confirm=false 应被拒
        a1 = await call(c, "accept_manuscript", project_root=ROOT, novel_id=NOVEL, chapter_id="ch_001", confirm=False)
        print("4. accept(confirm=false):", a1.get("ok"), "| code:", a1.get("code"))

        # 5. confirm=true 生效
        a2 = await call(c, "accept_manuscript", project_root=ROOT, novel_id=NOVEL, chapter_id="ch_001", confirm=True)
        print("5. accept(confirm=true):", a2.get("ok"), "| op:", str(a2.get("result"))[:120])

        # 6. 导出 EPUB
        ex = await call(c, "export_book", project_root=ROOT, novel_id=NOVEL,
                        output="/Users/jiaoziang/openjiu/demo-works/exports/demo_novel.epub",
                        title="夜班便利店", author="openwrite-novel-swarm")
        print("6. export_book ok:", ex.get("ok"), "| path:", ex.get("path"), "| validation:", str(ex.get("validation"))[:120])

asyncio.run(main())
