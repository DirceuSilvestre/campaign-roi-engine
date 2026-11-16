"""Módulo de gerenciamento e inspeção de schema do Lakehouse Eleitoral.

Carrega o mapeamento estruturado do arquivo schema_lakehouse.json, fornecendo
consultas de tipos de dados, verificação de existência de tabelas/colunas e
busca de correspondências aproximadas para o mecanismo de auto-reparo.
"""

import json
from difflib import get_close_matches
from pathlib import Path
from typing import Dict, List, Optional


class SchemaManager:
    """Gerenciador de schema para o Lakehouse Eleitoral C-Level."""

    def __init__(self, schema_json_path: str = "./schema_lakehouse.json") -> None:
        """Inicializa o gerenciador carregando o arquivo de schema JSON.

        Args:
            schema_json_path (str): Caminho para o arquivo schema_lakehouse.json.

        Raises:
            FileNotFoundError: Se o arquivo de schema não for localizado.
        """
        self.schema_path = Path(schema_json_path)
        self.total_tabelas: int = 0
        self.tabelas_schema: Dict[str, List[Dict[str, str]]] = {}
        self._carregar_schema()

    def _carregar_schema(self) -> None:
        """Lê e estrutura o dicionário de schema a partir do arquivo JSON."""
        if not self.schema_path.exists():
            raise FileNotFoundError(
                f"Arquivo de schema não encontrado em '{self.schema_path}'. "
                "Execute 'py extraction-schema.py' para gerá-lo."
            )

        with open(self.schema_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        self.total_tabelas = payload.get("total_tabelas", 0)
        self.tabelas_schema = payload.get("tabelas", {})

    def obter_tabelas(self) -> List[str]:
        """Retorna a lista de todas as tabelas registradas no schema.

        Returns:
            List[str]: Nomes das tabelas disponíveis no Lakehouse.
        """
        return list(self.tabelas_schema.keys())

    def obter_colunas_tabela(self, nome_tabela: str) -> List[str]:
        """Retorna todas as colunas de uma tabela específica.

        Args:
            nome_tabela (str): Nome da tabela.

        Returns:
            List[str]: Lista de nomes das colunas da tabela.
        """
        tabela_lower = nome_tabela.lower().strip()
        if tabela_lower not in self.tabelas_schema:
            return []
        return [col_info["coluna"] for col_info in self.tabelas_schema[tabela_lower]]

    def obter_tipo_coluna(self, nome_tabela: str, nome_coluna: str) -> Optional[str]:
        """Obtém o tipo de dado de uma coluna específica.

        Args:
            nome_tabela (str): Nome da tabela.
            nome_coluna (str): Nome da coluna.

        Returns:
            Optional[str]: Tipo de dado (ex: 'VARCHAR', 'DOUBLE', 'BIGINT') ou None.
        """
        tabela_lower = nome_tabela.lower().strip()
        coluna_lower = nome_coluna.lower().strip()

        if tabela_lower in self.tabelas_schema:
            for col_info in self.tabelas_schema[tabela_lower]:
                if col_info["coluna"].lower() == coluna_lower:
                    return col_info["tipo"]
        return None

    def encontrar_coluna_mais_proxima(
        self, nome_coluna_errada: str, nome_tabela: Optional[str] = None
    ) -> Optional[str]:
        """Localiza a coluna existente mais próxima do nome incorreto fornecido.

        Args:
            nome_coluna_errada (str): Nome da coluna que gerou o erro sintático.
            nome_tabela (Optional[str]): Nome da tabela de contexto, se conhecida.

        Returns:
            Optional[str]: Nome da coluna mais próxima ou None.
        """
        todas_colunas: List[str] = []

        if nome_tabela and nome_tabela.lower() in self.tabelas_schema:
            todas_colunas = self.obter_colunas_tabela(nome_tabela)
        else:
            for cols in self.tabelas_schema.values():
                todas_colunas.extend([c["coluna"] for c in cols])

        correspondencias = get_close_matches(
            nome_coluna_errada, todas_colunas, n=1, cutoff=0.5
        )
        return correspondencias[0] if correspondencias else None