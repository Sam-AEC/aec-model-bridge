<div align="center">

<img src="../../assets/logo.svg" alt="AEC Model Bridge logo: an isometric model cube with a bridge arch" height="120">

[English](../../README.md) | [简体中文](README.zh-CN.md) | [Español](README.es.md) | [हिन्दी](README.hi.md) | **العربية** | [Português (BR)](README.pt-BR.md) | [Русский](README.ru.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Bahasa Indonesia](README.id.md) | [Türkçe](README.tr.md) | [한국어](README.ko.md) | [Tiếng Việt](README.vi.md) | [Italiano](README.it.md) | [Polski](README.pl.md) | [繁體中文](README.zh-TW.md)

<div dir="rtl">

> تمت هذه الترجمة بمساعدة الذكاء الاصطناعي. المرجع الأساسي هو ملف [README](../../README.md) الإنجليزي، ونرحّب بالتصحيحات عبر pull request (راجع [CONTRIBUTING.md](../../CONTRIBUTING.md)).

</div>

**اسأل الذكاء الاصطناعي عن نموذج Revit المفتوح لديك. لا يتغيّر شيء قبل أن توافق أنت.**

خادم MCP مفتوح المصدر وإضافة أصلية لبرنامج Revit 2024 – 2027. يعمل مع Claude وCodex وعملاء MCP الآخرين.

[![CI](https://img.shields.io/github/actions/workflow/status/Sam-AEC/aec-model-bridge/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/Sam-AEC/aec-model-bridge/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Sam-AEC/aec-model-bridge?style=flat-square&color=0F766E)](https://github.com/Sam-AEC/aec-model-bridge/releases/latest)
[![Revit](https://img.shields.io/badge/Revit-2024--2027-0696D7?style=flat-square)](#إصدارات-revit-المدعومة)
[![License](https://img.shields.io/badge/license-GPL--3.0%20%2B%20commercial-2563EB?style=flat-square)](../../LICENSING.md)

[ابدأ الآن](#البدء-السريع) | [أمثلة على سير العمل](#أمثلة-على-سير-العمل) | [الأدوات](../tools-generated.md) | [التوثيق](#التوثيق) | [التنزيل](https://github.com/Sam-AEC/aec-model-bridge/releases/latest)

</div>

<div dir="rtl">

<p align="center">
  <img src="../images/readme/banner.png" alt="AEC Model Bridge: مراجعة التعديلات التي يقترحها الذكاء الاصطناعي والموافقة عليها داخل Revit" width="900">
</p>

اربط Claude أو Codex أو أي عميل MCP آخر بنموذج Revit المفتوح لديك. يجمع AEC Model Bridge بين خادم MCP مكتوب بلغة Python وإضافة Revit أصلية: الأدوات للقراءة فقط تفحص النموذج فورًا، أما أي تغيير في النموذج فيتطلب افتراضيًا خطة معتمدة. [اطّلع على آلية الموافقة](#كيف-تعمل-الموافقة).

يتضمن الخادم نفسه فحص ملفات IFC وأتمتة Rhino وGrasshopper والتكامل مع Speckle. يبيّن [حالة التكاملات](#تكاملات-أخرى) المزوّدات المتاحة وتلك التي ما زالت قيد التطوير.

## أمثلة على سير العمل

لمنسّقي BIM: افحص جودة النموذج، وراجع العناصر المتأثرة، ووافق على تصحيح المعاملات (parameters)، ثم تحقق من النتائج وصدّر تقريرًا. تستخدم هذه الأمثلة أدوات من [الفهرس الحالي](../tools-generated.md).

| سير العمل | مثال على الطلب | الأدوات المستخدمة |
| --- | --- | --- |
| مراجعة النموذج | "اعرض المستند النشط، وأدرج تحذيراته، وابحث عن العناصر المتأثرة." | `revit_get_document_info`, `revit_get_warnings`, `revit_get_elements_by_type` |
| تحديث المعاملات | "ابحث عن الجدران في Level 02، واعرض قيم Comments الخاصة بها، واقترح تحديثًا دفعيًا." | `revit_get_elements_by_type`, `revit_get_element_parameters`, `revit_batch_set_parameters` |
| إنتاج المخططات | "جهّز قائمة لوحات (sheets) من ملف CSV هذا، ثم اقترح إنشاء اللوحات ووضع المناظير (views)." | `revit_batch_create_sheets_from_csv`, `revit_place_viewport_on_sheet` |
| مراجعة IFC | "اعرض طوابق ملف IFC هذا، وافحص خصائص الجدران، وأبلغ عن مشكلات التحقق من المخطط." | `ifc_get_spatial_structure`, `ifc_get_properties`, `ifc_validate` |

لتجربة أولى داخل Revit، جرّب ما يلي:

</div>

```text
Read the active model's warnings. Group them by description and show the
affected element IDs. Then suggest which issues to investigate first.
```

<div dir="rtl">

ثم جرّب تصحيح معامل، مع استبدال المستوى والقيمة بما يناسب مشروعك:

</div>

```text
Find walls on Level 02 and show their current Comments values. Propose setting
Comments to "Coordination reviewed" for the elements I choose. After I approve
the plan in Revit, apply it and read the values back to confirm the result.
```

<div dir="rtl">

في التعديلات، ينشئ المساعد خطة باستخدام `plan_actions`؛ وتراجعها أنت في لوحة Revit قبل أن يطبّقها `execute_plan`. مراجعة IFC تعمل دون Revit.

تتطلب وحدات QA/QC والتقارير القائمة على اللقطات (snapshots) لقطة محفوظة متوافقة. ويحتاج تمرير اللقطة حاليًا من Revit إلى الوحدة إلى تطابق اسم الملف ومساحة العمل؛ وقد يؤدي حذف `snapshot_id` إلى إرجاع بيانات نموذجية مولَّدة. استخدم أدوات Revit المباشرة أعلاه للفحص الحي. [الإصلاحات المخططة والعرض التجريبي](../roadmap.md).

## البدء السريع

**التثبيت بنقرة واحدة**

[![Install in VS Code](https://img.shields.io/badge/Install_in-VS_Code-0098FF?style=for-the-badge)](../install-buttons.md#vs-code)
[![Install in Cursor](https://img.shields.io/badge/Install_in-Cursor-111111?style=for-the-badge)](https://cursor.com/en/install-mcp?name=aec-model-bridge&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJnaXQraHR0cHM6Ly9naXRodWIuY29tL1NhbS1BRUMvYWVjLW1vZGVsLWJyaWRnZSNzdWJkaXJlY3Rvcnk9cGFja2FnZXMvbWNwLXNlcnZlci1yZXZpdCIsImFlYy1tb2RlbC1icmlkZ2UiXSwiZW52Ijp7Ik1DUF9SRVZJVF9NT0RFIjoiYnJpZGdlIn19)
[![Claude Desktop bundle](https://img.shields.io/badge/Claude_Desktop-.mcpb_bundle-D97757?style=for-the-badge)](https://github.com/Sam-AEC/aec-model-bridge/releases/latest)

تحتاج الأزرار إلى [uv](https://docs.astral.sh/uv/getting-started/installation/) فقط دون أي إعداد آخر: يستخدم الخادم المجلد `~/Documents/AEC Model Bridge` كمساحة عمل ما لم تحدد مساحتك الخاصة. بالنسبة إلى Claude Desktop، نزّل ملف `.mcpb` من أحدث إصدار وافتحه. ما زال العمل الحي مع Revit يتطلب Revit و[الإضافة](#تثبيت-إضافة-revit)؛ أما الوضع التجريبي (mock) فلا يحتاج إلى شيء.

**الإعداد اليدوي**

للأتمتة الحية في Revit تحتاج إلى Windows، ونسخة مرخّصة من Revit من 2024 إلى 2027، وPython 3.11 أو أحدث، و[uv](https://docs.astral.sh/uv/getting-started/installation/)، وإضافة Revit ([خطوات التثبيت](#تثبيت-إضافة-revit)). ثم أضف ما يلي إلى ملف `claude_desktop_config.json` (يستخدم Codex وCursor وVS Code القيم نفسها؛ ومتغيرا المجلدين اختياريان ويشيران افتراضيًا إلى مساحة العمل المذكورة أعلاه):

</div>

```json
{
  "mcpServers": {
    "aec-model-bridge": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit",
        "aec-model-bridge"
      ],
      "env": {
        "MCP_REVIT_MODE": "bridge",
        "MCP_REVIT_WORKSPACE_DIR": "C:\\RevitProjects",
        "MCP_REVIT_ALLOWED_DIRECTORIES": "C:\\RevitProjects"
      }
    }
  }
}
```

<div dir="rtl">

هل تريد الاطلاع على الأدوات أولًا دون Revit؟ اضبط `"MCP_REVIT_MODE": "mock"`. عندئذٍ يعمل الخادم في أي مكان، ويسرد كل الأدوات مع مخططاتها، ويعيد ردودًا جاهزة دون أن يلمس أي نموذج. يوجد ملف `Dockerfile` للوضع التجريبي نفسه في جذر المستودع (`docker build -t aec-model-bridge .` ثم `docker run -i --rm aec-model-bridge`).

تستخدم VS Code؟ يسجّل [مصدر الامتداد وخطوات التثبيت المحلي](../../extensions/vscode/README.md) خادم MCP ويعرض حالة الاتصال بـ Revit. لم يُنشر الامتداد في Marketplace.

### نظرة سريعة على الأدوات

| المجال | الأدوات | ماذا تفعل |
| --- | --- | --- |
| Revit | 103 | قراءة النموذج، وإنشاء العناصر والمعاملات والمناظير واللوحات والجداول وتحريرها، والتصدير، والعمل المشترك (worksharing) |
| الموافقة | 6 | تخطيط تغييرات النموذج ومراجعتها واعتمادها وتنفيذها والتراجع عنها |
| الوحدات | 34 | فحص اللقطات، وشبكات المعاملات، وفحوص QA/QC، والوصفات، والتقارير، والتحديدات |
| Rhino وGrasshopper | 19 | الهندسة، والطبقات، والخامات، والعمليات المنطقية (boolean) |
| Speckle | 17 | المشاريع، والنماذج، والإصدارات، والإرسال والاستقبال |
| Navisworks | 15 | شجرة النموذج، ونقاط الرؤية، واختبارات التعارض (قيد التطوير) |
| IFC | 7 | قراءة ملفات IFC دون Revit: البنية، والخصائص، والتحقق |
| الرسم البياني، واللقطات، والتصدير، والمهام | 18 | تدقيق الرسم البياني الدلالي، وفروق اللقطات، والتصدير إلى SQLite، والمهام الخلفية |

تُدرج 219 أداة في الإعداد الافتراضي (عُدّت من الخادم الحالي في الوضع التجريبي mock). تظهر أدوات Autodesk Data عند ضبط بيانات اعتماد APS. يسرد [مرجع الأدوات](../tools-generated.md) كل أداة. تحمل كل أداة تعليقات MCP التوضيحية (`readOnlyHint` و`destructiveHint` و`idempotentHint` و`openWorldHint`)، ليتمكّن العملاء من التمييز بين القراءة والكتابة.

### أتمتة Revit المتقدمة

إلى جانب استعلامات النموذج وتحديثات المعاملات، تنشئ أدوات Revit عناصر المباني والمناظير واللوحات والجداول والوسوم والأبعاد، وتصدّر ملفات IFC وDWG والصور وملفات Navisworks. راجع [مرجع الأدوات](../tools-generated.md) للاطلاع على العمليات والمدخلات المدعومة.

لما لا يغطيه فهرس الأدوات، تعمل `revit_invoke_method` و`revit_reflect_get` و`revit_reflect_set` مع أعضاء واجهة Revit API العامة، وتشغّل `revit_execute_python` شيفرة IronPython داخل Revit. لهذه الأدوات المتقدمة الصلاحيات نفسها التي لعملية Revit. لا تستخدمها إلا مع عملاء MCP وprompts تثق بها.

## كيف يعمل

يتحدث عميل MCP مع موزّع (hub) واحد مكتوب بـ Python. يرسل الموزّع كل استدعاء إلى المزوّد الذي يملك الأداة. وتتحدث مزوّدات تطبيقات سطح المكتب عبر localhost مع إضافة صغيرة داخل ذلك التطبيق.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../images/architecture-dark.png">
    <img src="../images/architecture-light.png" alt="Architecture of AEC Model Bridge: an MCP client such as Claude or Codex calls the Python MCP hub, which routes tool calls to the Revit, Rhino, Navisworks, IFC and Speckle providers. The Revit and Rhino providers talk to add-ins over localhost HTTP, the IFC provider reads IFC files with IfcOpenShell, and Navisworks is still in progress." width="900">
  </picture>
</p>

<sub>مصدر المخطط: [architecture.mmd](../diagrams/architecture.mmd). أعد توليد الصور بالأمر `python scripts/render_diagrams.py`.</sub>

الصناديق ذات اللون الأخضر المزرق تعمل اليوم. الصناديق ذات الحدود المتقطعة بلون العنبر قيد التطوير. أما الأشكال النيلية فهي البيانات والخدمات الخارجية.

### كيف تعمل الموافقة

يوقف الموزّع أي استدعاء لأداة يغيّر النموذج ما لم يحمل خطة معتمدة. الوضع الافتراضي هو `required`. يقترح الذكاء الاصطناعي خطة، وتراجعها أنت في اللوحة الجانبية في Revit، ثم تنفّذها الإضافة على الخيط الرئيسي في Revit ضمن معاملة (transaction) مسمّاة.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Sam-AEC/aec-model-bridge/main/docs/images/readme/readme-workflow-dark.png">
    <img src="https://raw.githubusercontent.com/Sam-AEC/aec-model-bridge/main/docs/images/readme/readme-workflow-light.png" alt="Inspect, Propose, Approve, Verify. Four steps: inspect finds an empty Mark, propose drafts a change, approve is a human decision, verify reads the value back. Example values are illustrative." width="900">
  </picture>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../images/approval-flow-dark.png">
    <img src="../images/approval-flow-light.png" alt="Approval flow: the AI assistant proposes a plan, the MCP hub and ApprovalGate show it in the Revit side panel, and only after you approve does execute_plan forward the commands to the Revit add-in, which runs them in one named transaction. If you reject or never approve, the call is blocked and the model stays untouched." width="900">
  </picture>
</p>

<sub>مصدر المخطط: [approval-flow.mmd](../diagrams/approval-flow.mmd). أعد توليد الصور بالأمر `python scripts/render_diagrams.py`.</sub>

إذا اعتُمدت خطة ثم تبيّن لاحقًا أنها خاطئة، فإن `rollback_plan` يعكسها. يستخدم التراجع أمر Undo في Revit ضمن الجلسة نفسها أو القيم العكسية للمعاملات. أما العمليات التي لا يمكن عكسها، مثل كتابة الملفات، فتطلب تأكيدًا ثانيًا. دورة الحياة موضحة في [ADR 0008](../0008-approval-gate-lifecycle.md).

لخطوط المعالجة غير المراقبة يمكنك ضبط `MCP_REVIT_APPROVAL_MODE=auto`. يؤدي ذلك إلى إيقاف المراجعة البشرية، لذا استخدمه في بيئة خاضعة للتحكم فقط.

## إصدارات Revit المدعومة

| إصدار Revit | هدف الإضافة | أدوات البناء |
|---|---|---|
| 2024 | .NET Framework 4.8 | .NET 8 SDK وحزمة المطوّر لـ .NET Framework 4.8 |
| 2025 | .NET 8 for Windows | .NET 8 SDK |
| 2026 | .NET 8 for Windows | .NET 8 SDK |
| 2027 | .NET 10 for Windows | .NET 10 SDK |

تحتاج أيضًا إلى Windows 10 أو 11، وPython 3.11 أو أحدث، ونسخة Revit مرخّصة للإصدار الذي تستخدمه. يشغّل الوضع التجريبي (mock) الخادم دون Revit، وهو مفيد للتطوير والاختبار.

### تكاملات أخرى

| التكامل | الحالة |
|---|---|
| Revit | متاح. إضافة أصلية بلغة C#. |
| IFC (IfcOpenShell) | متاح. يقرأ ملفات IFC دون الحاجة إلى تشغيل Revit. |
| Rhino وGrasshopper | متاح. يتصل بإضافة Rhino على `localhost:3004`. |
| Speckle | متاح. يحتاج إلى معرّف عميل Speckle في بيئتك. |
| Navisworks Manage | قيد التطوير. المزوّد وأدواته مسجّلان، لكن إضافة Navisworks لم تكتمل. |
| Power BI | قيد التطوير. المزوّد والأداة موجودان لكنهما غير مسجّلين في الموزّع. |
| Excel وParquet وDuckDB | مخطط له. |

## تثبيت إضافة Revit

**الأسهل (Windows):** نزّل `AECModelBridge-Setup-<version>.exe` من [أحدث إصدار](https://github.com/Sam-AEC/aec-model-bridge/releases/latest)، وانقر عليه نقرًا مزدوجًا، واختر إصدارات Revit لديك، ثم أعد تشغيل Revit. يثبّت الإضافة وخادم Python المرفق، وإذا حددت الخيار فيثبّت أيضًا إعدادات Claude Desktop وVS Code مع نسخة احتياطية من إعداداتك الحالية. يمكنك إلغاء التثبيت من إعدادات Windows. الخطوات أدناه مخصصة للبناء من المصدر.

عليك تثبيت جزأين: خادم MCP بلغة Python وإضافة Revit. تحتاج الأتمتة الحية في Revit إلى كليهما.

### 1. تثبيت خادم MCP

</div>

```powershell
git clone https://github.com/Sam-AEC/aec-model-bridge.git
cd aec-model-bridge

py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e packages/mcp-server-revit
```

<div dir="rtl">

### 2. تثبيت إضافة Revit

اضبط الإصدار ليطابق تثبيت Revit لديك. إذا حظر Windows السكربتات التي نزّلتها، فانقر بزر الفأرة الأيمن على كل ملف `.ps1`، وافتح Properties، واختر Unblock قبل تشغيلها.

</div>

```powershell
$RevitVersion = Read-Host "Revit year (2024, 2025, 2026, or 2027)"

.\scripts\package.ps1 -RevitVersion $RevitVersion
.\scripts\install.ps1 -RevitVersion $RevitVersion
```

<div dir="rtl">

يضع المثبّت الملفات التنفيذية الخاصة بكل إصدار في:

</div>

```text
C:\ProgramData\AECModelBridge\bin\<year>
```

<div dir="rtl">

يُثبَّت ملف بيان الإضافة (manifest) لكل مستخدم في:

</div>

```text
%APPDATA%\Autodesk\Revit\Addins\<year>
```

<div dir="rtl">

استخدم `-AllUsers` مع `install.ps1` لتثبيت ملف البيان في `C:\ProgramData\Autodesk\Revit\Addins\<year>` بدلًا من ذلك.

لتجهيز الملفات التنفيذية لكل الإصدارات المدعومة دفعة واحدة:

</div>

```powershell
.\scripts\package.ps1 -RevitVersion All
```

<div dir="rtl">

يتضمن كل [إصدار على GitHub](https://github.com/Sam-AEC/aec-model-bridge/releases/latest) حزمة جاهزة لكل سنة من Revit، مثل `aec-model-bridge-revit-2026-<version>.zip`. فك ضغطها ثم شغّل `.\install.ps1 -RevitVersion 2026` بدلًا من البناء من المصدر. ولإنشاء مثبّت Windows بنقرة مزدوجة، يبنيه السكربت `scripts/build-installer.ps1` باستخدام Inno Setup. الدليل الكامل، مع استكشاف الأخطاء، في [docs/install.md](../install.md).

## ربط Claude Desktop بـ Revit

أضف الخادم إلى إعدادات عميل MCP لديك. في Claude Desktop هو قسم `mcpServers` في `claude_desktop_config.json`. يستخدم Codex وCursor وVS Code وغيرها من عملاء MCP قيم `command` و`args` و`env` نفسها بصيغة الإعداد الخاصة بكل منها.

استخدم ملف Python التنفيذي من بيئتك الافتراضية، واختر مجلد مساحة عمل يُسمح للخادم بالوصول إليه:

</div>

```json
{
  "mcpServers": {
    "aec-model-bridge": {
      "command": "C:\\path\\to\\aec-model-bridge\\.venv\\Scripts\\python.exe",
      "args": ["-m", "revit_mcp_server.mcp_server"],
      "env": {
        "MCP_REVIT_MODE": "bridge",
        "MCP_REVIT_WORKSPACE_DIR": "C:\\RevitProjects",
        "MCP_REVIT_ALLOWED_DIRECTORIES": "C:\\RevitProjects"
      }
    },
    "aec-model-bridge-revit-2026": {
      "command": "C:\\path\\to\\aec-model-bridge\\.venv\\Scripts\\python.exe",
      "args": ["-m", "revit_mcp_server.mcp_server"],
      "env": {
        "MCP_REVIT_MODE": "bridge",
        "MCP_REVIT_HOST_VERSION": "2026",
        "MCP_REVIT_WORKSPACE_DIR": "C:\\RevitProjects",
        "MCP_REVIT_ALLOWED_DIRECTORIES": "C:\\RevitProjects"
      }
    }
  }
}
```

<div dir="rtl">

احذف `MCP_REVIT_HOST_VERSION` لاستهداف أحدث نسخة Revit مفتوحة. واضبطه على سنة مثل `2024` أو `2026` لتثبيت إدخال العميل على ذلك الإصدار من Revit. يتجاوز `MCP_REVIT_BRIDGE_URL` نقطة الاتصال في الإعدادات المتقدمة.

يمكن لمستخدمي VS Code البدء من [`.vscode/mcp.json`](../../.vscode/mcp.json). ويمكن لمستخدمي Hermes Desktop البدء من [`docs/examples/hermes-desktop.json`](../examples/hermes-desktop.json) بعد استبدال مسار Python النموذجي. ويمكن للعملاء الذين يدعمون MCP Bundles تثبيت ملف `.mcpb` من [أحدث إصدار](https://github.com/Sam-AEC/aec-model-bridge/releases/latest). وتبقى إضافة Revit مطلوبة لأن الخادم يتحدث مع تطبيق سطح المكتب العامل.

### التحقق من الاتصال

أعد تشغيل Revit بعد تثبيت الإضافة، وافتح نموذجًا، ثم نفّذ:

</div>

```powershell
$registry = Get-ChildItem "$env:LOCALAPPDATA\AECModelBridge\registry\revit-*.json" | Select-Object -First 1
$switch = Get-Content $registry.FullName -Raw | ConvertFrom-Json
Invoke-RestMethod "$($switch.endpoint)/health"
```

<div dir="rtl">

يجب أن يُظهر الرد `healthy` وإصدار Revit العامل. في Revit، ابحث عن علامة التبويب `AEC Bridge` في الشريط. تضم لوحة Workflows الأوامر Open Panel وHealth Check وPending Actions وReports. وتضم لوحة Tools الأوامر Config وHelp وAbout.

## الأمان

- يستمع جسر Revit على localhost فقط.
- يقرأ الخادم ويكتب داخل المجلدات المذكورة في `MCP_REVIT_ALLOWED_DIRECTORIES` فقط.
- تحتاج الأدوات التي تغيّر النموذج إلى خطة معتمدة ما لم توقف الموافقة.
- تُسجَّل استدعاءات الأدوات في سجل تدقيق، وتُحجب الأسرار.

التفاصيل في [docs/security.md](../security.md). للإبلاغ عن ثغرة أمنية، اتبع [SECURITY.md](../../SECURITY.md).

## الأسئلة الشائعة

### ما هو خادم MCP لبرنامج Revit؟

بروتوكول Model Context Protocol (MCP) معيار مفتوح يتيح لمساعدي الذكاء الاصطناعي استدعاء أدوات في برامج أخرى. ينشر خادم MCP لبرنامج Revit عمليات Revit على هيئة أدوات. يختار المساعد الأدوات، وتنفّذها الإضافة داخل Revit.

### ما مساعدو الذكاء الاصطناعي الذين يعملون معه؟

أي عميل MCP قادر على تشغيل خادم stdio محلي. نوثّق Claude Desktop وVS Code مع GitHub Copilot والعملاء الذين يقرؤون إعداد `mcpServers` القياسي. ويمكن لمحادثة اللوحة أيضًا استخدام مفتاح Anthropic API أو أداتي سطر الأوامر `claude` أو `codex` إذا كانتا مثبّتتين. راجع [ADR 0012](../0012-native-agent-chat-backend.md).

### هل يستطيع الذكاء الاصطناعي تغيير نموذجي دون أن يسأل؟

ليس في الوضع الافتراضي. تُحجب الأدوات التي تغيّر النموذج حتى تُعتمد خطة في لوحة Revit. وتعمل الأدوات للقراءة فقط دون موافقة. وإذا ضبطت `MCP_REVIT_APPROVAL_MODE=auto` فستُتجاوز الموافقة.

### هل يرسل نموذجي إلى السحابة؟

يعمل الخادم والإضافة على جهازك، ويستمع الجسر على localhost. وما يراه مساعد الذكاء الاصطناعي يعتمد على العميل الذي تستخدمه: تذهب نتائج الأدوات إلى مزوّد النموذج لدى ذلك العميل. أما المزوّدات المرتبطة بالسحابة، مثل Speckle، فلا تعمل إلا عند ضبطها واستدعاء أدواتها.

### هل يعمل مع ملفات IFC دون Revit؟

نعم. يقرأ مزوّد IFC الملفات باستخدام IfcOpenShell. يمكنه إرجاع بيانات الملف الوصفية والبنية المكانية وخصائص العناصر والصناديق المحيطة (bounding boxes)، وتنفيذ استعلامات بحسب الفئة أو GUID أو الاسم أو الخاصية، والتحقق من المخطط. ولا يحرّر ملفات IFC.

### هل يمكنني استخدامه دون تثبيت Revit؟

يمكنك تشغيل الخادم في الوضع التجريبي (mock) للتطوير والاختبار. أما العمل الحي على النموذج فيحتاج إلى Revit من 2024 إلى 2027 والإضافة.

## الإصدارات والنسخ

يتبع AEC Model Bridge نظام الإصدارات الدلالي. توسم الإصدارات على GitHub بالصيغة `vX.Y.Z`، ويحمل ملف `VERSION` في الجذر رقم الإصدار. راجع [docs/versioning.md](../versioning.md) لعملية الإصدار، و[CHANGELOG.md](../../CHANGELOG.md) لما تغيّر في كل إصدار.

## التطوير

</div>

```powershell
# Python tests
python -m pytest packages/mcp-server-revit/tests

# Build one Revit version, for example 2026
.\scripts\build-addin.ps1 -RevitVersion 2026 -Configuration Release

# Build all supported versions
.\scripts\package.ps1 -RevitVersion All
```

<div dir="rtl">

يبني CI خادم Python وأهداف الإضافة لإصدارات Revit من 2024 إلى 2027. راجع [CONTRIBUTING.md](../../CONTRIBUTING.md) قبل فتح pull request.

## التوثيق

- [دليل التثبيت](../install.md)
- [مرجع الأدوات](../tools-generated.md)
- [البنية المعمارية](../0001-multi-provider-architecture.md)
- [مرجع الإعدادات](../configuration-reference.md)
- [الأمان](../security.md)
- [عملاء MCP والسجل](../marketplaces.md)
- [الإصدارات والنسخ](../versioning.md)
- [كل التوثيق](../README.md)
- [دليل المساهمة](../../CONTRIBUTING.md) و [مدونة السلوك](../../CODE_OF_CONDUCT.md)
- [المساهمون](../../CONTRIBUTORS.md)

## المشروع والترخيص

يتولى صيانته [A. Sam Mohammad](https://github.com/Sam-AEC).
[LinkedIn](https://www.linkedin.com/in/a-sam-mohammad-92790416b) |
[Issues](https://github.com/Sam-AEC/aec-model-bridge/issues)

[GPL-3.0-or-later مع استثناء الربط بـ Revit (Revit Linking Exception)، أو ترخيص تجاري](../../LICENSING.md).

</div>
