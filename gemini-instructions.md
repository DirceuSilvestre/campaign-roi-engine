# MASTER SPECIFICATION: Sistema de Inteligência Estratégica Eleitoral C-Level
# VERSION: 3.0.0
# STATUS: Documento Mestre de Arquitetura e Engenharia (Specification-First)

---

## 1. VISÃO GERAL E PROPÓSITO COMERCIAL

### 1.1 Objetivo Comercial
O sistema destina-se à geração automatizada de Dossiês Analíticos e Estratégicos Eleitorais em formato PDF executivo. Seu foco é apoiar a tomada de decisões de alta relevância por executivos eleitorais exigentes e consumidores do mercado de serviços de ultra luxo.

### 1.2 Público-Alvo e Ergonomia de Comunicação
- **Perfil do Cliente/Leitor**: Candidatos com escolaridade a partir do ensino médio completo e comitês estratégicos C-Level.
- **Tom e Linguagem**: Tradução de conceitos matemáticos e estatísticos complexos para uma linguagem clara, direta, livre de jargões técnicos áridos e focada em recomendações acionáveis de negócio.
- **Princípio do Retorno sobre o Investimento**: Toda análise financeira deve responder à pergunta central do cliente: *"Onde colocar o próximo R$ 1.000,00 para obter o maior volume de novos votos ao menor custo?"*

---

## 2. ARQUITETURA DE SOFTWARE E PADRÕES DE PROJETO

### 2.1 Estrutura de Diretórios (Src-Layout)

projeto/
├── data/                            # Diretório de dados brutos (TSE e IBGE)
│   ├── IBGE/
│   ├── 20**/
│   │   ├── candidato/
│   │   ├── eleitorado/
│   │   ├── receita/
│   │   └── votacao/
│   ├── lakehouse_eleitoral/
│   ├── src/
│   │   ├── database/
│   │   └── etl/
├── extraction-schema.py
├── run_pipeline.py
├── schema_lakehouse.json
└── gemini-instructions.md

### 2.2 Padrões de Projeto OBRIGATÓRIOS

- **Idempotência**: Garantir que executar o mesmo pipeline de dados várias vezes com os mesmos parâmetros produza exatamente o mesmo resultado, sem duplicar registros.
- **Particionamento de Dados**: Organizar grandes volumes de dados por dimensões temporais (ano, mês, dia, hora) para otimizar custos de leitura e performance de queries.
- **Deduplicação com Janela (Window Deduplication)**: Identificar e remover eventos duplicados ou retransmitidos por APIs de terceiros dentro de uma janela temporal específica.
- **Dead Letter Queue (DLQ)**: Direcionar registros corrompidos ou que falharam na validação de schema para uma fila de tratamento, evitando que o pipeline inteiro quebre.
- **Data Observability (Observabilidade de Dados)**: Aplicar checagens contínuas de qualidade (data contracts, contagem de linhas, nulidade e freshness) para detectar falhas antes que os consumidores finais percebam.
- **Single Responsibility Principle (SRP)**: Cada módulo e classe possui uma única responsabilidade. A camada de banco (`DatabaseConnection`) não gera gráficos, e a camada de visualização (`ExecutiveChartRenderer`) não executa SQL.
- **SOLID & Clean Code**: Interfaces explícitas, funções pequenas, desacoplamento e imutabilidade de dados de transferência.
- **Google Style Docstrings**: Todas as funções, classes e métodos devem possuir docstrings detalhando propósito, `Args:`, `Returns:` e `Raises:`.

---

## 3. ENGENHARIA DE DADOS, ETL E LAKEHOUSE

### 3.1 Stack Tecnológica Justificada
- **Formato de Armazenamento**: Apache Parquet com compressão Snappy. Garante armazenamento colunar eficiente e redução drástica do I/O de disco.
- **Motor de Consultas**: DuckDB (em memória / in-process C++). Permite vetorização SIMD, zero-copy de arquivos Parquet e execução nativa de dialeto SQL avançado sem infraestrutura de servidor.

### 3.2 Ingestão e Varredura Agnośtica de Subpastas
O pipeline de carga deve ler recursivamente todas as subpastas dentro de `./data/`, independente da profundidade ou do nome das pastas, capturando extensões `.csv`, `.txt`, `.xls`, `.xlsx` e `.gpkg`.

### 3.3 Sanitização Blind / Data-Driven na Carga
Nenhuma higienização de strings ou chaves deve ocorrer na camada de apresentação/SQL. A carga ETL aplica:
1. **Chaves e Identificadores (`sanitizar_id`)**: Remoção de decimais (`.0`), espaços e conversão para string limpa em colunas identificadas como ID ou chaves primárias/estrangeiras (`id_candidato`, `ano_eleicao`, `codigo_municipio_tse`, `zona_eleitoral`, `secao_eleitoral`).
2. **Textos e Nomes (`sanitizar_texto_generico`)**: Trim nas pontas e colapso de múltiplos espaços internos para um único espaço em branco (`re.sub(r"\s+", " ", s)`).
3. **Valores Monetários (`converter_moeda_brl_para_float`)**: Conversão do padrão BRL (`R$ 1.500,00`) para `float` (`1500.0`).
4. **Contagens e Inteiros**: Conversão direta para `int64` preenchendo nulos com `0`.
5. **Tradução Facilitada de Colunas**: Substituição automática de siglas e códigos codificados do IBGE e TSE por nomes descritivos em português leigo e deduplicados (`traduzir_colunas_dataframe`).

---

## 4. EXTRAÇÃO DO SCHEMA DO LAKEHOUSE (`schema_lakehouse.json`)

1. A extração do schema é **totalmente independente** da execução do pipeline ETL.
2. O script `extraction-schema.py` realiza o re-escaneamento dinâmico e tempo-real de todas as views Parquet gravadas em `./lakehouse_eleitoral/`.
3. O schema capturado é salvo no arquivo físico `schema_lakehouse.json`, contendo o mapeamento exato de tabelas, colunas descritivas e seus respectivos tipos de dados (`VARCHAR`, `DOUBLE`, `BIGINT`).
4. O arquivo `schema_lakehouse.json` é estruturado com marcadores de contexto prontos para anexação no prompt de Text-to-SQL da LLM.

---

## 5. DIALETO SQL, EXECUÇÃO E AUTO-REPARO SINTÁTICO

### 5.1 Regras de Dialeto DuckDB
- **Harmonização de Textos**: Uso de `strip_accents(UPPER(coluna)) = strip_accents(UPPER('termo'))` para ignorar acentuação e caixa de texto.
- **Igualdade Estrita em Chaves**: Junções e filtros por `id_candidato` e `ano_eleicao` utilizam comparação exata (`=`) sem uso de `LIKE` ou `REGEXP_REPLACE` em tempo de execução.
- **Tratamento Nulo**: Todas as somas e métricas utilizam `COALESCE(SUM(...), 0)`.

### 5.2 Auto-Reparo Sintático Automatizado em 2ª Tentativa
1. O método `executar_consulta(query_sql)` em `DatabaseConnection` executa a consulta enviada no DuckDB.
2. Se o DuckDB disparar uma exceção de erro sintático (`duckdb.ParserException`, `duckdb.CatalogException` ou `duckdb.BinderException`), o sistema captura a mensagem exata do erro.
3. O manipulador de auto-reparo aplica correções determinísticas de acordo com a categoria da falha:
   - **Erro de Coluna Inexistente**: Mapeia a coluna mais próxima no schema ativo e reescreve a query.
   - **Erro de Aspas/Escalamento de String**: Ajusta aspas duplas de identificadores e aspas simples de literais.
   - **Erro de Tipo de Dado / Comparação**: Aplica cast explícito de tipos (`CAST(coluna AS VARCHAR)`).
4. O sistema executa automaticamente a segunda tentativa com a query corrigida. Se a falha persistir, lança uma exceção tratada detalhando a causa raiz.

---

## 6. COORTES DEMOGRÁFICOS E DATAVIZ DO ESTADO DA ARTE

### 6.1 Agrupamento Demográfico por Coortes do IBGE
Para reduzir a carga cognitiva visual e evitar sobreposição de rótulos em dados de perfil de eleitorado por faixa etária, as consultas SQL ou o pré-processamento do código devem agrupar micro-idades nas 4 categorias oficiais de Coorte do IBGE:
1. `1. Jovem (16-24)`: Inclui 16 a 24 anos.
2. `2. Adulto Jovem (25-44)`: Inclui 25 a 44 anos.
3. `3. Adulto Maduro (45-59)`: Inclui 45 a 59 anos.
4. `4. Sênior (60+)`: Inclui 60 anos ou mais.

### 6.2 Escolha Gráfica por Intenção Analítica
| Intenção Analítica | Modelo Gráfico | Parâmetro | Aplicação Executiva |
| :--- | :--- | :--- | :--- |
| **Comparação de Magnitudes** | Lollipop Chart (Pirulito) | `"lollipop"` | Votação por Zona ou Bairro. |
| **Composição e Proporção** | Donut com KPI Central | `"donut"` | Distribuição de gastos pelos 4 Pilares. |
| **Mudança em 2 Pontos** | Slopechart | `"slopechart"` | Comparação Eleições 2020 vs 2024. |
| **Trajetória de Ranking** | Bump Chart | `"bump"` | Evolução de posição entre candidatos. |
| **Alcance de Metas / Quotas** | Waffle Chart (Grade 10x10) | `"waffle"` | Proporção de eleitorado atingido. |
| **Evolução Temporal / Perfil** | Ridgeline / Area Plot | `"area"` | Evolução de receitas/despesas ou faixas etárias. |

### 6.3 Regras de Ergonomia Visual
- **Rotulagem Direta (*Direct Labeling*)**: Eliminação de legendas distantes; rótulos posicionados diretamente nos elementos visuais.
- **Cromatismo Funcional**: Uso de paleta neutra com destaque na cor principal do partido ou candidato.
- **Títulos Declarativos**: Substituição de títulos genéricos por afirmações conclusivas.
- **Formatação BRL e Inteiros**: Valores monetários obrigatoriamente formatados no padrão pt-BR (`R$ 1.500,00`) e inteiros formatados sem decimais (`1.500`).

---

## 7. MATEMÁTICA ECONOMÉTRICA ELEITORAL

### 7.1 Custo por Voto Real Global ($CPV_{\text{real}}$)
$$CPV_{\text{real}} = \frac{D_{\text{total, pago}}}{V_{\text{totais}}}$$
Onde $D_{\text{total, pago}}$ representa o somatório das despesas contratadas/pagas declaradas no TSE e $V_{\text{totais}}$ o total de votos válidos obtidos.

### 7.2 Índice de Potencial de Retorno Marginal ($IPR_z$) — "Oceano Azul"
Identifica onde cada R$ 1.000,00 adicionais gerarão o maior volume de novos votos:
$$IPR_z = \frac{\text{Aptos}_z - V_z}{\text{Aptos}_z} \cdot \left(1 + \ln\left(\frac{\text{Aptos}_z}{CPV_{z, \text{hist}} + 1}\right)\right)$$

### 7.3 Índice Prescritivo de Alocação de Capital ($IPAC_z$)
Direciona a distribuição de novos aportes financeiros entre zonas eleitorais com base no saldo de eleitores não convertidos e no custo histórico de aquisição.

---

## 8. DIRETRIZES DE COMPORTAMENTO PARA A IA COLABORADORA (AGENT GUIDELINES)

Toda Inteligência Artificial que atuar no desenvolvimento ou manutenção deste ecossistema DEVE seguir rigorosamente as seguintes diretrizes:

1. **Avaliação Integral Prévia**:
   A IA está expressamente proibida de tomar decisões ou gerar código antes de analisar **todos os arquivos em anexo** e o **prompt completo do usuário**.
2. **Pesquisa Ativa e Embasamento Científico/Técnico**:
   Diante de dúvidas de arquitetura, otimização de consultas, escolha de algoritmos ou conceitos estatísticos/jurídicos, a IA deve realizar pesquisas e fundamentar todas as respostas e soluções com base científica e estado da arte técnico.
3. **Princípio da Generalização Orientada a Dados**:
   O código gerado deve ser totalmente genérico e agnóstico a nomes de arquivos, pastas ou candidatos específicos. Deve aplicar o princípio da generalização, tratando os dados com base nos seus **tipos de variáveis** (`VARCHAR`, `FLOAT`, `BIGINT`, `DATETIME`) e estruturas de dados específicas da linguagem Python (DataFrames, Dicionários, Dataclasses).
4. **Postura de Programador Sênior e Responsabilidade**:
   A IA deve codificar como um programador sênior e cientista de dados experiente, utilizando as estruturas de dados mais adequadas para cada problema, assumindo responsabilidade total pela qualidade, eficiência, robustez e elegância do código gerado.

---

## 9. ESTRATÉGIA DE TESTES UNITÁRIOS (TDD & PADRÃO AAA)

- **Estrutura de Testes**: Todos os módulos em `src/` devem ter seu correspondente de teste unitário em `tests/unit/`.
- **Padrão Arrange-Act-Assert (AAA)**:
  - **Arrange**: Configuração das pré-condições, fixtures e entradas.
  - **Act**: Execução da função ou método sob teste.
  - **Assert**: Verificação rigorosa das saídas e efeitos colaterais.
- **Cobertura Obrigatória de Cenários**:
  - **Caminho Feliz (*Happy Path*)**: Entradas perfeitamente formatadas retornando a estrutura esperada.
  - **Casos de Borda (*Edge Cases*)**: Strings vazias, valores `None`, números decimais em IDs (`"123.0"`), espaços múltiplos e acentuação mista.
  - **Tratamento de Erros**: Captura e validação de exceções sintáticas de SQL e arquivos corrompidos.

---

## 10. CHECKLIST DE AUTOAVALIAÇÃO C-LEVEL

Antes de considerar qualquer entrega ou relatório como concluído, o sistema/desenvolvedor deve validar:
- [ ] O código-fonte contém zero *hardcodes* de candidatos, cidades ou caminhos de arquivos?
- [ ] Os dados foram higienizados exclusivamente na carga ETL e os IDs estão sem sufixos decimais?
- [ ] O relatório PDF está livre de sobreposição de rótulos gráficos, e as idades estão agrupadas em Coortes do IBGE?
- [ ] Os valores monetários estão no formato pt-BR (`R$ 1.500,00`) e as contagens em inteiros (`1.500`)?
- [ ] As recomendações analíticas contêm fundamentação econométrica ($CPV$, $IPR_z$)?

---

## 11. CONSULTA SQL DE QUALIDADE

Para atingir qualidade máxima e evitar alucinações de dados, a consulta deve ser estruturada em quatro fases encadeadas:

**1. Mapeamento de Contexto e Schema Linking Ativo**
Antes de gerar qualquer comando SQL, o sistema deve inspecionar a estrutura física exata do banco. No nosso ecossistema, isso é resolvido utilizando o arquivo `schema_lakehouse.json`, que fornece à inteligência o mapeamento tipado de todas as 17 tabelas (`VARCHAR`, `BIGINT`, `DOUBLE`). O **Schema Linking** associa os termos da linguagem natural diretamente aos nomes de colunas e tabelas reais (por exemplo, associando "gastos de campanha" a `despesas_pagas_candidatos_2024_rj.valor_pagamento_despesa`), eliminando adivinhações do modelo.

**2. Tradução Estrita para o Dialeto Nativo (DuckDB)**
A consulta precisa ser construída respeitando as especificações e otimizações do motor analítico em memória (DuckDB em C++):

* **Harmonização Textual Insensível a Acentos e Caixas**: Uso obrigatório de `strip_accents(UPPER(coluna)) = strip_accents(UPPER('termo'))` para que variações ortográficas no filtro não omitam registros válidos.
* **Comparação Exata de Chaves**: Filtros por identificadores e anos (`id_candidato = '12345'`, `ano_eleicao = '2024'`) devem utilizar igualdade estrita (`=`) e nunca operadores imprecisos como `LIKE`, garantindo a integridade relacional.
* **Tratamento de Nulos**: Agregações numéricas devem ser protegidas por `COALESCE(SUM(coluna), 0)` para evitar que valores nulos corrompam o cálculo final.

**3. Circuito de Validação e Auto-Reparo Sintático (Execution Feedback Loop)**
A garantia de qualidade ocorre na execução controlada. O sistema envia a query SQL gerada para a classe de conexão do DuckDB (`DatabaseConnection`). Se o motor disparar um erro de compilação ou catálogo (`ParserException` ou `BinderException`), o manipulador de auto-reparo captura a exceção exata, identifica o problema (como um tipo desalinhado ou coluna ausente), aplica a correção determinística (por exemplo, `CAST(coluna AS VARCHAR)`) e reexecuta a consulta em segunda tentativa antes de retornar o resultado ao usuário.

**4. Tradução Econométrica e Resposta C-Level**
A qualidade da resposta final não se resume a exibir linhas e colunas brutas. O resultado numérico deve ser traduzido em inteligência acionável, aplicando fórmulas econométricas do projeto como o Custo por Voto Real ($CPV_{\text{real}} = \frac{D_{\text{total, pago}}}{V_{\text{totais}}}$), o Índice de Potencial de Retorno Marginal ($IPR_z$) e o agrupamento demográfico em Coortes do IBGE (`1. Jovem`, `2. Adulto Jovem`, `3. Adulto Maduro`, `4. Sênior`), apresentados com formatação em moeda BRL (`R$ 1.500,00`) e números inteiros formatados.

---
