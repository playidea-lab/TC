"""정보이득 하이브리드 reranker — 켤레사전(Beta) spine + 저데이터 LLM prior.

요청별 retrieved top-K 이웃에서 recipe 사후분포를 일회성 fit하고, 기대
엔트로피 감소(정보이득) 순으로 랭킹한다. posterior는 응답 후 폐기 —
stateless 정체성과 정합. (/pi the-commons-infogain-reranker)
"""
