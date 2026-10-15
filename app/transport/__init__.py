"""传输脊（transport spine）：全部外部服务出网点的中立底座。

四域 provider（LLM/搜索/向量化/重排序）与采集/热榜的出网统一经本包——
HTTP 出口（http.py）、错误分类学（errors.py）、计量落账（metering.py）、
额度闸（quota.py）。能力域保留各自的重试模板方法与计量语义，横切面只有
这一份。设计依据见 docs/design-index.md「TR-1」。
"""
