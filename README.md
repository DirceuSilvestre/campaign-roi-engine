# Análise Eleitoral — ETL, Lakehouse e dossiês analíticos

Projeto de análise de dados eleitorais que transforma arquivos públicos do TSE e dados geográficos do IBGE em tabelas Parquet consultáveis e relatórios PDF. O fluxo combina um ETL executável em Python com uma etapa analítica iterativa, na qual consultas SQL e narrativas são preparadas com apoio de um modelo de linguagem e revisadas por uma pessoa.

O projeto demonstra trabalho com ingestão e transformação de dados, SQL analítico, DuckDB, visualização e comunicação de resultados. A interação com a LLM é manual: não há integração com API nem uma automação que execute as etapas de geração e revisão dos prompts de forma automática, pois devido aos riscos de alucinação e mesmo utilizando formas de mitigar os riscos, é necessário uma revisão humana.

## Visão geral do fluxo

```text
Arquivos brutos em data/
        │
        ▼
run_pipeline.py
Leitura, renomeação de colunas e sanitização
        │
        ▼
lakehouse_eleitoral/
Arquivos Parquet e banco DuckDB
        │
        ▼
extraction-schema.py
        │
        ▼
schema_lakehouse.json ───────────────┐
                                     │
gemini-instructions.md + pergunta  ──┤
                                     ▼
                 LLM gera/adapta código Python e SQL
                                     │
                                     ▼
                 Execução do código → PDF analítico
                                     │
                                     ▼
              Revisão do PDF com apoio de uma LLM
                                     │
                                     ▼
              Código revisado → dossiê final em PDF
```

As etapas de ETL e de produção dos relatórios são independentes. O ETL prepara ou atualiza os dados; a geração de um relatório consulta o Lakehouse já existente. As etapas com LLM dependem de envio manual de arquivos, instruções e resultados.

## 1. Preparação dos dados

### Entrada

O diretório `data/` contém arquivos organizados por ano e assunto. A estrutura presente inclui pastas para 2024 e 2026, com categorias como candidatos, eleitorado, receitas e votação, além de dados do IBGE. O ETL percorre subpastas recursivamente e reconhece `.csv`, `.txt`, `.xls`, `.xlsx` e `.gpkg`.

### Execução

Na raiz do projeto:

```bash
python run_pipeline.py
```

O script delega o processamento a `src/etl/ingestion.py`, que:

1. localiza arquivos nas extensões suportadas;
2. lê os dados — CSV/TXT com DuckDB, planilhas com pandas e GeoPackage com GeoPandas;
3. aplica o mapeamento de nomes de colunas definido em `src/etl/sanitizer.py`, incluindo traduções de códigos do TSE/IBGE quando previstas no mapeamento;
4. trata valores com regras baseadas nos nomes das colunas, como identificadores, textos, campos monetários e contagens;
5. grava cada tabela como Parquet com compressão Snappy em `lakehouse_eleitoral/` e registra uma tabela correspondente em `lakehouse_eleitoral/analytics.duckdb`.

Os nomes das tabelas são derivados dos nomes dos arquivos. O processo não depende de um servidor de banco de dados separado: DuckDB é executado localmente.

### Extração do schema

Depois de gerar ou atualizar os Parquet:

```bash
python extraction-schema.py
```

Esse script inspeciona os arquivos Parquet diretamente e grava `schema_lakehouse.json`, com nomes de tabelas, colunas e tipos. O arquivo serve como referência de estrutura para elaborar consultas e fornecer contexto a uma LLM.

## 2. Análise e geração dos dossiês

O fluxo usado para responder a uma pergunta analítica é interativo:

1. formular a pergunta de negócio ou de pesquisa;
2. fornecer à LLM as instruções de `gemini-instructions.md`, o schema atual e o código-base do relatório;
3. revisar a consulta SQL e o código gerados, ajustando-os quando necessário;
4. executar o código na raiz do projeto para consultar o Lakehouse e gerar um PDF com tabelas, indicadores e gráficos;
5. revisar o primeiro PDF e fornecer esse material à LLM para apoiar a elaboração de interpretações e conclusões;
6. revisar as novas análises, o SQL e o código resultante;
7. executar a versão final do código e revisar o dossiê antes de entregá-lo.

No repositório atual, `PRODUTO.py` é o exemplo de gerador analítico mais abrangente: reúne busca de informações do candidato, consultas, indicadores financeiros e eleitorais, tabelas e diferentes visualizações. Seu bloco `main()` contém uma configuração de exemplo específica; para outra análise, revise o candidato, o município, o ano, as perguntas, as queries, os títulos, os tipos de gráfico e as conclusões antes de executar.

O PDF final não é produzido por uma chamada automática à LLM. O texto interpretativo depende da análise feita a partir do primeiro PDF, de sua incorporação ao código e da revisão humana.

### Execução do exemplo incluído

```bash
python PRODUTO.py
```

Esse comando executa os valores definidos no `main()` do arquivo, que podem não corresponder à pergunta ou ao relatório desejado. A execução depende dos arquivos Parquet, do schema e das bibliotecas Python necessárias.

## Organização do repositório

| Caminho | Função |
|---|---|
| `data/` | Arquivos brutos usados como entrada do ETL. |
| `src/etl/ingestion.py` | Varredura, leitura e gravação do Lakehouse. |
| `src/etl/sanitizer.py` | Tradução de colunas e regras de sanitização. |
| `run_pipeline.py` | Ponto de entrada para executar a ingestão. |
| `lakehouse_eleitoral/` | Arquivos Parquet e banco DuckDB gerados ou usados pelo projeto. |
| `extraction-schema.py` | Gera o catálogo de tabelas e colunas dos Parquet. |
| `schema_lakehouse.json` | Schema exportado, usado como contexto para consultas e para a LLM. |
| `src/database/` | Conexão DuckDB, registro de views Parquet, acesso ao schema e execução de consultas. |
| `PRODUTO.py` | Exemplo de gerador de dossiê analítico com consultas, indicadores e gráficos. |
| `PROPAGANDA.py` | Outros geradores/versões de relatórios presentes no projeto; não são chamados pelo ETL. |
| `gemini-instructions.md` | Instruções de contexto e estilo analítico para uso manual com uma LLM. |
| `Dossie_Estrategico_*.pdf` | Relatórios existentes no diretório, apresentados como exemplos de saída; não são recriados pelo ETL. |

## Tecnologias e competências demonstradas

- **Python:** organização do processamento e geração de documentos.
- **Parquet:** armazenamento colunar dos dados processados.
- **LLMs com supervisão humana:** apoio à elaboração de consultas e à interpretação de resultados por meio de um fluxo manual.

## Escopo

Este projeto é um fluxo local de preparação e análise de dados eleitorais com geração de relatórios executivos. A etapa de ingestão é implementada em código; a formulação e revisão de perguntas, análises narrativas e recomendações com LLM ocorrem manualmente. Os resultados dependem das fontes disponíveis, das consultas selecionadas e da revisão aplicada em cada execução.
