# OpenDataLoader PDF API

使用 [opendataloader-pdf](https://github.com/opendataloader-project/opendataloader-pdf)
实现兼容的 `POST /file_parse` 接口。

## 启动

需要 [uv](https://docs.astral.sh/uv/)、Java 11+ 和 `pdfinfo`（Poppler）：

```bash
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

运行测试：

```bash
uv run pytest
```

也可以使用 Docker：

```bash
docker build -t opendataloader-pdf-api .
docker run --rm -p 8000:8000 -v "$PWD/output:/app/output" opendataloader-pdf-api
```

Swagger 文档：<http://localhost:8000/docs>

## 调用

```bash
curl -X POST 'http://localhost:8000/file_parse' \
  -F 'files=@./example.pdf' \
  -F 'return_md=true' \
  -F 'return_content_list=true' \
  -F 'return_images=true' \
  -o output.json
```

批量上传时重复使用 `files`：

```bash
curl -X POST 'http://localhost:8000/file_parse' \
  -F 'files=@./a.pdf' \
  -F 'files=@./b.pdf'
```

`start_page_id` 和 `end_page_id` 是从 0 开始且包含结束页。`backend=pipeline`
使用 OpenDataLoader 本地 Java 解析器；`backend=docling-fast` 使用 Hybrid 后端，需另行启动
`opendataloader-pdf-hybrid` 服务。

当前实现面向 PDF。OpenDataLoader 不原生支持 Office 文件，也没有与 MinerU 完全等价的
`formula_enable` / `table_enable` 开关；这些表单字段会被接受以保持调用兼容。

`content_list` 中的 `bbox` 与 MinerU 保持一致：格式为 `[x0, y0, x1, y1]`，
使用左上角原点，并依据每页实际宽高分别归一化到 `0-1000` 的整数范围。
