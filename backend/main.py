import uvicorn

import os
os.environ["NO_PROXY"] = "127.0.0.1,localhost"


if __name__ == "__main__":
    # 启动 FastAPI 服务，监听 0.0.0.0:8000 端口
    # 如果是在开发环境，可以加上 reload=True
    uvicorn.run("app.api:app", host="0.0.0.0", port=8000, reload=True)
