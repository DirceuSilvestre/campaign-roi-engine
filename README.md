<div align="center">
  <h1>📊 Inteligência Eleitoral: ETL, Lakehouse Local e Dossiês Analíticos</h1>
  <h3>Pipeline de engenharia de dados (TSE + IBGE) e geração de relatórios executivos em PDF com SQL analítico e fluxo Human-in-the-Loop.</h3>
  <p>De dados públicos brutos e heterogêneos a diagnósticos eleitorais e financeiros auditáveis.<br/><b>Python · DuckDB · Apache Parquet · GeoPandas · Schema-Grounded LLM (HITL).</b></p>

  <p>
    <a href="#arquitetura-do-fluxo">Arquitetura</a> ·
    <a href="#1-pipeline-de-etl-e-lakehouse">ETL & Lakehouse</a> ·
    <a href="#2-fluxo-analitico-human-in-the-loop">Fluxo Analítico (HITL)</a> ·
    <a href="#trade-offs-de-engenharia">Trade-offs</a> ·
    <a href="#organizacao-do-repositorio">Estrutura</a>
  </p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.10%2B-38bdf8?&logo=python&logoColor=white" alt="Python" />
    <img src="https://img.shields.io/badge/Engine-DuckDB-FFF000?&logo=duckdb&logoColor=black" alt="DuckDB" />
    <img src="https://img.shields.io/badge/Storage-Parquet_%28Snappy%29-10b981?" alt="Parquet" />
    <img src="https://img.shields.io/badge/AI_Workflow-Human--in--the--Loop-ec4899?" alt="HITL" />
  </p>

  <!-- Recomendação: adicione aqui um print lado a lado das páginas do Dossie_Estrategico_*.pdf -->
  <!-- <img src="images/preview_dossie.png" alt="Exemplo de Dossiê Analítico Gerado" width="90%"/> -->
</div>

> **Dados públicos não vêm prontos para decisão.** Arquivos do TSE e malhas/dados do IBGE possuem múltiplas extensões, códigos crípticos e tipagens inconsistentes. Este projeto resolve o ciclo completo: padroniza e armazena os dados em um Lakehouse local consultável via SQL e estrutura dossiês executivos em PDF combinando métricas financeiras/eleitorais com revisão humana assistida por IA.

---

## 🏗️ Arquitetura do Fluxo

O sistema desacopla a **engenharia de preparação dos dados** da **camada de análise e visualização**. O ETL constrói e atualiza o Lakehouse; os scripts analíticos consultam os arquivos Parquet já saneados para compilar os relatórios.

```text
Arquivos brutos em data/ (TSE: 2024, 2026 + IBGE)
        │  (.csv, .txt, .xls, .xlsx, .gpkg)
        ▼
run_pipeline.py  ──► src/etl/ingestion.py + sanitizer.py
        │            (Varredura recursiva, tradução de códigos e tipagem)
        ▼
lakehouse_eleitoral/
        ├── *.parquet (Armazenamento colunar com compressão Snappy)
        └── analytics.duckdb (Catálogo analítico local)
        │
        ▼
extraction-schema.py
        │
        ▼
schema_lakehouse.json ───────────────┐  (Catálogo de tabelas, colunas e tipos)
                                     │
gemini-instructions.md + pergunta  ──┤  (Regras de negócio e estilo analítico)
                                     ▼
                 LLM gera/adapta queries SQL e código Python
                                     │
                                     ▼
                 Execução local ──► 1ª versão do PDF (Tabelas + Gráficos)
                                     │
                                     ▼
                 Revisão humana + apoio da LLM na narrativa
                                     │
                                     ▼
                 Código revisado ──► Dossiê Final em PDF (Dossie_Estrategico_*.pdf)

```

---

## 1. Pipeline de ETL e Lakehouse

### Fontes e Ingestão Recursiva

O diretório `data/` organiza os insumos brutos por ano (como `2024` e `2026`) e domínio (candidatos, eleitorado, receitas, votação e bases do IBGE). Ao executar:

```bash
python run_pipeline.py

```

O orquestrador (`src/etl/ingestion.py`) percorre recursivamente as subpastas e aplica leitores específicos conforme o formato de origem:

* **`.csv` e `.txt`:** Leitura de alta performance diretamente via **DuckDB**.
* **`.xls` e `.xlsx`:** Processamento tabular via **Pandas**.
* **`.gpkg` (GeoPackage):** Leitura de dados geográficos via **GeoPandas**.

### Sanitização Determinística e Camada Parquet

Antes da gravação, `src/etl/sanitizer.py` aplica regras de higienização baseadas na semântica das colunas:

* **Tradução de Metadados:** Conversão de siglas e códigos originais do TSE/IBGE para nomes descritivos legíveis.
* **Tipagem Estrita:** Normalização de identificadores, limpeza de strings, conversão de campos monetários e padronização de contagens.
* **Persistência Colunar:** Cada tabela é gravada em formato **Parquet (compressão Snappy)** dentro de `lakehouse_eleitoral/` e registrada no banco local `lakehouse_eleitoral/analytics.duckdb`, dispensando servidores externos.

### Extração de Catálogo para IA (`Schema Grounding`)

```bash
python extraction-schema.py

```

Este script inspeciona fisicamente os arquivos Parquet gerados e exporta o `schema_lakehouse.json` contendo todas as tabelas, colunas e tipos de dados reais. Esse catálogo serve tanto como documentação técnica quanto como **âncora de contexto** para evitar que a LLM invente nomes de colunas ao escrever SQL.

---

## 2. Fluxo Analítico (*Human-in-the-Loop*)

A geração dos dossiês não utiliza chamadas automáticas de API nem delega decisões cegas à IA. Por conta dos riscos de alucinação em análises quantitativas, o projeto adota um **fluxo iterativo supervisionado**:

1. **Formulação da Pergunta:** Definição do recorte analítico (candidato, município, ano e objetivo da análise).
2. **Contexto Controlado:** Envio manual do `schema_lakehouse.json`, das diretrizes em `gemini-instructions.md` e do script-base para a LLM propor ou adaptar as consultas SQL.
3. **Auditoria de Código e SQL:** Revisão humana das queries geradas antes da execução no DuckDB.
4. **Prototipação Visual:** Execução do script para gerar a primeira versão do PDF com indicadores financeiros/eleitorais, tabelas e gráficos.
5. **Refinamento Narrativo:** Submissão do primeiro PDF para apoiar a redação das interpretações, seguida de nova revisão humana nos textos e no código antes da emissão do dossiê final.

### Executando o Relatório de Exemplo

O arquivo `PRODUTO.py` reúne um caso completo de análise (busca cadastral do candidato, cruzamento de receitas/votação, indicadores, tabelas e visualizações). Para executá-lo com os parâmetros configurados em seu bloco `main()`:

```bash
python PRODUTO.py

```

*(Para analisar outro candidato, município ou pleito, basta ajustar os parâmetros, queries e títulos diretamente no `main()` antes da execução).*

---

## ⚖️ Trade-offs de Engenharia e Decisões de Escopo

| Decisão Arquitetural | Escolha Adotada | Justificativa e Trade-off Assumido |
| --- | --- | --- |
| **Motor Analítico e Storage** | **DuckDB + Parquet (Snappy)** em disco local. | Elimina custos e complexidade de manter um servidor PostgreSQL/Cloud ativo, mantendo consultas SQL analíticas rápidas sobre milhões de linhas. |
| **Orquestração com LLM** | **Fluxo Manual (*Human-in-the-Loop*)** sem integração via API. | **Trade-off consciente:** abre mão da automação ponta a ponta para garantir zero custo de API, aproveitamento máximo de contexto e bloqueio de alucinações via revisão humana obrigatória. |
| **Catálogo de Schema** | Geração independente via `extraction-schema.py`. | Garante que o `schema_lakehouse.json` reflita exatamente o estado físico dos arquivos Parquet, desacoplando a ingestão da etapa de análise. |

---

## 📁 Organização do Repositório

| Caminho | Responsabilidade |
| --- | --- |
| `data/` | Arquivos brutos de entrada (bases do TSE 2024/2026 e IBGE). |
| `run_pipeline.py` | Ponto de entrada CLI para execução completa do ETL. |
| `src/etl/ingestion.py` | Varredura recursiva, leitura multi-formato e escrita em Parquet/DuckDB. |
| `src/etl/sanitizer.py` | Dicionário de tradução de colunas (TSE/IBGE) e regras de sanitização. |
| `lakehouse_eleitoral/` | Camada de dados processados (`.parquet`) e catálogo `analytics.duckdb`. |
| `extraction-schema.py` | Extrator dinâmico de metadados dos arquivos Parquet. |
| `schema_lakehouse.json` | Schema físico exportado para consulta e contexto da LLM. |
| `src/database/` | Camada de conexão DuckDB, registro de views Parquet e execução de queries. |
| `PRODUTO.py` | Gerador principal de dossiê analítico (consultas, indicadores, gráficos e PDF). |
| `PROPAGANDA.py` | Variação de gerador analítico voltado a análises específicas de campanha. |
| `gemini-instructions.md` | Prompt estruturado com regras de estilo analítico e formatação para a LLM. |
| `Dossie_Estrategico_*.pdf` | Exemplos reais de relatórios executivos gerados pelo projeto. |

---

## 🛠️ Competências e Tecnologias Aplicadas

* **Engenharia de Dados & ETL:** Python, Pandas, GeoPandas, varredura recursiva de arquivos, higienização de dados e normalização de esquemas.
* **Arquitetura Lakehouse & SQL:** Apache Parquet (compressão Snappy), DuckDB e SQL analítico para cruzamento de bases eleitorais e demográficas.
* **Data Visualization & Reporting:** Geração programática de relatórios executivos em PDF combinando tabelas, indicadores financeiros/eleitorais e gráficos.
* **Governança de IA Generativa:** Engenharia de prompt (`gemini-instructions.md`), *Schema Grounding* (`schema_lakehouse.json`) e validação *Human-in-the-Loop*.

---

## 🤝 Contato

Projeto desenvolvido para demonstrar habilidades práticas em **Análise de Dados, Engenharia de Analytics e Arquitetura de Decisão, uso e interação da IA durante o processo de trabalho**.

* ![LinkedIn](https://img.shields.io/badge/Linkedin-@dirceu--silvestre-0A66C2?style=flat-square&labelColor=075A9B)
* [![Outlook](https://shields.io/badge/Email-dirceu__silvestre-0A66C2?style=flat-square&labelColor=075A9B)](mailto:dirceu_silvestre@hotmail.com)
