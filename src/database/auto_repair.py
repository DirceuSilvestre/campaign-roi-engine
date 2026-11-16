"""Módulo de auto-reparo sintático e reescrita determinística de SQL.

Analisa mensagens de erro do DuckDB (ParserException, CatalogException, BinderException)
e aplica correções automatizadas em 2ª tentativa, incluindo mapeamento de colunas
próximas, ajuste de aspas e coerção explícita de tipos (CAST).
"""

import re
from typing import Tuple
from src.database.schema_manager import SchemaManager


class SQLAutoRepair:
    """Mecanismo de auto-reparo determinístico para consultas DuckDB."""

    def __init__(self, schema_manager: SchemaManager) -> None:
        """Inicializa o auto-reparador com uma instância do gerenciador de schema.

        Args:
            schema_manager (SchemaManager): Gerenciador ativo do schema_lakehouse.json.
        """
        self.schema_manager = schema_manager

def reparar_query(self, query_sql: str, mensagem_erro: str) -> Tuple[str, str]:
    query_corrigida = query_sql
    
    coluna_match = re.search(
        r'Referenced column "([^"]+)" not found|Column with name ([^\s]+) does not exist',
        mensagem_erro,
        re.IGNORECASE,
    )
    if coluna_match:
        coluna_errada = (coluna_match.group(1) or coluna_match.group(2)).replace("'", "").replace('"', "")
        
        # Extrai a tabela alvo da cláusula FROM para restringir a busca de colunas
        tabela_match = re.search(r'FROM\s+([a-zA-Z0-9_]+)', query_sql, re.IGNORECASE)
        nome_tabela = tabela_match.group(1) if tabela_match else None
        
        coluna_proxima = self.schema_manager.encontrar_coluna_mais_proxima(
            coluna_errada, nome_tabela=nome_tabela
        )

        if coluna_proxima and coluna_proxima != coluna_errada:
            query_corrigida = re.sub(
                rf"\b{re.escape(coluna_errada)}\b",
                coluna_proxima,
                query_corrigida,
                flags=re.IGNORECASE,
            )
            return query_corrigida, f"Mapeada coluna inexistente '{coluna_errada}' para '{coluna_proxima}'."

        return query_corrigida, "Falha na correção automática."
    

        # Categoria 2: Erro de Aspas ou Escalamento de Literais
        if "syntax error at or near" in mensagem_erro.lower() or "parser" in mensagem_erro.lower():
            query_corrigida = re.sub(r'"([a-zA-Z0-9_\s\-]+)"', r"'\1'", query_corrigida)
            motivo = "Ajustado escalamento de aspas em literais textuais."
            if query_corrigida != query_sql:
                return query_corrigida, motivo

        # Categoria 3: Erro de Comparação de Tipos de Dados
        tipo_match = re.search(
            r"Cannot compare|Type mismatch|Cannot cast",
            mensagem_erro,
            re.IGNORECASE,
        )
        if tipo_match:
            query_corrigida = re.sub(
                r"(\w+)\s*=\s*('[\w\s\-]+')",
                r"CAST(\1 AS VARCHAR) = \2",
                query_corrigida,
            )
            motivo = "Aplicado CAST explícito para VARCHAR em filtro de comparação."
            return query_corrigida, motivo

        return query_corrigida, motivo