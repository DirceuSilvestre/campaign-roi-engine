"""Orquestrador e Gerador de Dossiês Estratégicos Eleitorais C-Level em PDF.

Módulo otimizado: focado exclusivamente em perfil demográfico, dominância territorial,
engenharia financeira (CPV) e análises gráficas prescritivas de alto impacto.
"""

from dataclasses import dataclass
import datetime
import io
import math
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Union
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import HRFlowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

try:
    from src.database.connection import DatabaseConnection
except Exception:
    from connection import DatabaseConnection


def remover_acentos(texto: str) -> str:
    """Remove acentuação e caracteres especiais de uma string para nomes de arquivos."""
    mapa_acentos = {
        'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'ä': 'a',
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ó': 'o', 'ò': 'o', 'õ': 'o', 'ô': 'o', 'ö': 'o',
        'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
        'ç': 'c', 'ñ': 'n',
        'Á': 'A', 'À': 'A', 'Ã': 'A', 'Â': 'A', 'Ä': 'A',
        'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E',
        'Í': 'I', 'Ì': 'I', 'Î': 'I', 'Ï': 'I',
        'Ó': 'O', 'Ò': 'O', 'Õ': 'O', 'Ô': 'O', 'Ö': 'O',
        'Ú': 'U', 'Ù': 'U', 'Û': 'U', 'Ü': 'U',
        'Ç': 'C', 'Ñ': 'N'
    }
    for orig, subst in mapa_acentos.items():
        texto = texto.replace(orig, subst)
    return texto


def gerar_nome_arquivo_pdf(nome_urna: str, prefixo: str = "Dossie_Estrategico") -> str:
    """Gera um nome de arquivo PDF dinâmico com nome de urna e carimbo temporal seguro."""
    nome_limpo = re.sub(r'[^a-zA-Z0-9]', '_', remover_acentos(nome_urna)).strip('_')
    nome_limpo = re.sub(r'_+', '_', nome_limpo)
    timestamp = datetime.datetime.now().strftime("%d%m%Y_%H%M")
    return f"{prefixo}_{nome_limpo}_{timestamp}.pdf"


def construir_filtro_candidato_sql(
    id_candidato: Optional[str] = None,
    cpf_candidato: Optional[str] = None,
    numero_candidato: Optional[str] = None,
    municipio: Optional[str] = None,
    nome_urna: Optional[str] = None,
    nome_completo: Optional[str] = None,
    incluir_cpf: bool = True,
    con=None,
    nome_tabela: Optional[str] = None
) -> str:
    """Gera uma cláusula de filtro SQL multi-chave universal e compatível com todas as tabelas do Lakehouse."""
    valores_invalidos = {'', '0', '0.0', '0,0', '#nulo#', '-1', '-4', 'none', 'nan', 'null'}
    condicoes = []

    colunas_disponiveis = None
    if con is not None and nome_tabela:
        try:
            df_cols = con.execute(f"DESCRIBE {nome_tabela}").df()
            colunas_disponiveis = set(df_cols["column_name"].str.lower().tolist())
        except Exception:
            colunas_disponiveis = None

    def coluna_existe(nome_col: str) -> bool:
        if colunas_disponiveis is None:
            return True
        return nome_col.lower() in colunas_disponiveis

    if coluna_existe("id_candidato") and id_candidato and str(id_candidato).strip().lower() not in valores_invalidos:
        id_limpo = str(id_candidato).strip()
        condicoes.append(f"CAST(id_candidato AS VARCHAR) = '{id_limpo}'")

    if incluir_cpf and coluna_existe("cpf_candidato") and cpf_candidato and str(cpf_candidato).strip().lower() not in valores_invalidos:
        cpf_limpo = str(cpf_candidato).strip()
        condicoes.append(f"CAST(cpf_candidato AS VARCHAR) = '{cpf_limpo}'")

    col_mun = None
    if coluna_existe("nome_ue"):
        col_mun = "nome_ue"
    elif coluna_existe("nome_municipio"):
        col_mun = "nome_municipio"

    if coluna_existe("numero_candidato") and col_mun and numero_candidato and municipio:
        if str(numero_candidato).strip().lower() not in valores_invalidos:
            num_limpo = str(numero_candidato).strip()
            mun_esc = str(municipio).strip().replace("'", "''")
            condicoes.append(
                f"(CAST(numero_candidato AS VARCHAR) = '{num_limpo}' AND "
                f"strip_accents(UPPER(CAST({col_mun} AS VARCHAR))) = strip_accents(UPPER('{mun_esc}')))"
            )

    col_nome = None
    if coluna_existe("nome_candidato"):
        col_nome = "nome_candidato"
    elif coluna_existe("nome_urna_candidato"):
        col_nome = "nome_urna_candidato"

    nome_alvo = nome_completo or nome_urna
    if col_nome and col_mun and nome_alvo and municipio:
        if str(nome_alvo).strip().lower() not in valores_invalidos:
            nome_esc = str(nome_alvo).strip().replace("'", "''")
            mun_esc = str(municipio).strip().replace("'", "''")
            condicoes.append(
                f"(strip_accents(UPPER(CAST({col_nome} AS VARCHAR))) LIKE strip_accents(UPPER('%{nome_esc}%')) AND "
                f"strip_accents(UPPER(CAST({col_mun} AS VARCHAR))) = strip_accents(UPPER('{mun_esc}')))"
            )

    if condicoes:
        return f"({' OR '.join(condicoes)})"

    return "(1=0)"


@dataclass
class ItemAnaliseEstrategica:
    pergunta: str
    titulo_grafico: str
    query_sql: str
    conclusao_negocio: Optional[str] = None
    modelo_grafico: str = "lollipop"


class NumberedCanvasExecutivo(canvas.Canvas):
    """Canvas customizado para rodapé confidencial com carimbo de data/hora e paginação dinâmica."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: List[Dict] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.desenhar_rodape_executivo(num_pages)
            super().showPage()
        super().save()

    def desenhar_rodape_executivo(self, total_paginas: int) -> None:
        self.saveState()
        self.setFont("Helvetica-Bold", 7)
        self.setFillColor(colors.HexColor("#64748B"))
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.6)

        self.line(36, 28, 595.27 - 36, 28)

        data_atual = datetime.datetime.now().strftime("%d/%m/%Y")
        mensagem_rodape = (
            f"CONFIDENCIAL • USO EXCLUSIVO DO COMITÊ ESTRATÉGICO | GERADO EM {data_atual}"
        )
        self.drawString(36, 16, mensagem_rodape)
        self.drawRightString(595.27 - 36, 16, f"Página {self._pageNumber} de {total_paginas}")
        self.restoreState()


class ExecutiveChartRenderer:
    """Renderizador central de rotinas gráficas C-Level em Matplotlib para relatórios PDF."""

    @staticmethod
    def renderizar(
        df: pd.DataFrame, col_label: str, col_valor: str, modelo: str = "lollipop"
    ) -> io.BytesIO:
        if df is None or df.empty:
            return ExecutiveChartRenderer._gerar_grafico_vazio()

        modelo = str(modelo).lower().strip()
        if modelo == "donut":
            return ExecutiveChartRenderer.gerar_grafico_donut(df, col_label, col_valor)
        elif modelo == "slopechart":
            return ExecutiveChartRenderer.gerar_grafico_slopechart(df, col_label, col_valor)
        elif modelo == "bump":
            return ExecutiveChartRenderer.gerar_grafico_bump(df, col_label, col_valor)
        elif modelo == "waffle":
            return ExecutiveChartRenderer.gerar_grafico_waffle(df, col_label, col_valor)
        elif modelo == "area":
            return ExecutiveChartRenderer.gerar_grafico_area(df, col_label, col_valor)
        else:
            return ExecutiveChartRenderer.gerar_grafico_lollipop(df, col_label, col_valor)

    @staticmethod
    def _gerar_grafico_vazio() -> io.BytesIO:
        fig, ax = plt.subplots(figsize=(6.8, 2.2), dpi=300)
        ax.text(
            0.5, 0.5, "Sem dados suficientes para exibição gráfica",
            ha="center", va="center", fontsize=9, color="#64748B", fontweight="bold"
        )
        ax.axis("off")
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf

    @staticmethod
    def gerar_grafico_lollipop(df: pd.DataFrame, col_label: str, col_valor: str) -> io.BytesIO:
        plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
        fig, ax = plt.subplots(figsize=(6.8, 2.2), dpi=300)

        df_plot = df.head(5).copy()
        labels = [str(x)[:28] for x in df_plot[col_label].tolist()][::-1]
        valores = [float(x) for x in df_plot[col_valor].tolist()][::-1]
        y_pos = np.arange(len(labels))

        ax.hlines(y=y_pos, xmin=0, xmax=valores, color="#0F172A", linewidth=1.5, zorder=2)
        ax.plot(valores, y_pos, "o", color="#0284C7", markersize=7, zorder=3)

        max_val = max(valores) if valores and max(valores) > 0 else 1.0
        for v, y in zip(valores, y_pos):
            val_txt = f"{v:,.0f}".replace(",", ".")
            ax.text(v + (max_val * 0.02), y, val_txt, va="center", ha="left", fontsize=7.5, fontweight="bold", color="#0F172A")

        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=7.5, fontweight="bold", color="#1E293B")
        ax.set_xlim(0, max_val * 1.25)
        ax.spines[:].set_visible(False)
        ax.xaxis.grid(True, linestyle="--", alpha=0.5, color="#E2E8F0")
        ax.yaxis.grid(False)

        plt.subplots_adjust(left=0.25, right=0.88, top=0.92, bottom=0.15)
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf

    @staticmethod
    def gerar_grafico_donut(df: pd.DataFrame, col_label: str, col_valor: str) -> io.BytesIO:
        plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
        fig, ax = plt.subplots(figsize=(6.8, 2.2), dpi=300)

        df_plot = df.head(5).copy()
        labels = [str(x)[:22] for x in df_plot[col_label].tolist()]
        valores = [float(x) for x in df_plot[col_valor].tolist()]

        cores = ["#0284C7", "#0F172A", "#64748B", "#38BDF8", "#CBD5E1"]
        ax.pie(
            valores,
            labels=labels,
            autopct="%1.1f%%",
            startangle=90,
            colors=cores[:len(valores)],
            pctdistance=0.72,
            textprops=dict(color="#0F172A", fontsize=7.0, fontweight="bold"),
        )

        centre_circle = plt.Circle((0, 0), 0.55, fc="white")
        fig.gca().add_artist(centre_circle)

        total_val = sum(valores)
        total_txt = f"R$ {total_val:,.0f}".replace(",", ".") if total_val > 10000 else f"{total_val:,.0f}".replace(",", ".")
        ax.text(0, 0, f"Total\n{total_txt}", ha="center", va="center", fontsize=8.0, fontweight="bold", color="#0284C7")

        ax.axis("equal")
        plt.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.05)
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf

    @staticmethod
    def gerar_grafico_slopechart(df: pd.DataFrame, col_label: str, col_valor: str) -> io.BytesIO:
        plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
        fig, ax = plt.subplots(figsize=(6.8, 2.2), dpi=300)

        num_cols = [c for c in df.columns if c != col_label and pd.api.types.is_numeric_dtype(df[c])]

        if len(num_cols) >= 2:
            col_x1, col_x2 = num_cols[0], num_cols[1]
            df_plot = df.head(5).copy()

            for _, row in df_plot.iterrows():
                label = str(row[col_label])[:20]
                val1 = float(row[col_x1])
                val2 = float(row[col_x2])

                color = "#0284C7" if val2 >= val1 else "#64748B"
                ax.plot([0, 1], [val1, val2], "o-", color=color, linewidth=1.8, markersize=6)
                ax.text(-0.04, val1, f"{label}: {val1:,.0f}".replace(",", "."), ha="right", va="center", fontsize=7, fontweight="bold", color="#0F172A")
                ax.text(1.04, val2, f"{val2:,.0f}".replace(",", "."), ha="left", va="center", fontsize=7, fontweight="bold", color=color)

            ax.set_xticks([0, 1])
            ax.set_xticklabels([str(col_x1), str(col_x2)], fontsize=8, fontweight="bold", color="#0F172A")
            ax.set_xlim(-0.35, 1.35)
        else:
            df_plot = df.head(2).copy()
            labels = df_plot[col_label].astype(str).tolist()
            valores = df_plot[col_valor].astype(float).tolist()

            if len(valores) == 2:
                color = "#0284C7" if valores[1] >= valores[0] else "#64748B"
                ax.plot([0, 1], [valores[0], valores[1]], "o-", color=color, linewidth=2, markersize=7)
                ax.text(-0.04, valores[0], f"{labels[0]}: {valores[0]:,.0f}".replace(",", "."), ha="right", va="center", fontsize=7.5, fontweight="bold")
                ax.text(1.04, valores[1], f"{labels[1]}: {valores[1]:,.0f}".replace(",", "."), ha="left", va="center", fontsize=7.5, fontweight="bold", color=color)
                ax.set_xticks([0, 1])
                ax.set_xticklabels([labels[0], labels[1]], fontsize=8, fontweight="bold")
                ax.set_xlim(-0.35, 1.35)

        ax.spines[:].set_visible(False)
        ax.yaxis.set_visible(False)
        ax.grid(False)

        plt.subplots_adjust(left=0.25, right=0.85, top=0.88, bottom=0.18)
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf

    @staticmethod
    def gerar_grafico_bump(df: pd.DataFrame, col_label: str, col_valor: str) -> io.BytesIO:
        plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
        fig, ax = plt.subplots(figsize=(6.8, 2.2), dpi=300)

        num_cols = [c for c in df.columns if c != col_label and pd.api.types.is_numeric_dtype(df[c])]

        if len(num_cols) >= 2:
            df_plot = df.head(5).copy()
            ranks = df_plot[num_cols].rank(ascending=False, method="min")
            x_steps = np.arange(len(num_cols))

            cores = ["#0284C7", "#0F172A", "#64748B", "#0284C7", "#CBD5E1"]

            for i, (_, row_rank) in enumerate(ranks.iterrows()):
                item_label = str(df_plot.iloc[i][col_label])[:18]
                y_ranks = row_rank.values
                c = cores[i % len(cores)]

                ax.plot(x_steps, y_ranks, "o-", color=c, linewidth=2, markersize=7)
                ax.text(-0.08, y_ranks[0], item_label, ha="right", va="center", fontsize=7, fontweight="bold", color="#0F172A")

                for x, r in zip(x_steps, y_ranks):
                    ax.text(x, r, f"{int(r)}º", ha="center", va="center", fontsize=5.5, fontweight="bold", color="white")

            ax.set_xticks(x_steps)
            ax.set_xticklabels([str(c) for c in num_cols], fontsize=8, fontweight="bold", color="#0F172A")
            ax.set_xlim(-0.3, len(num_cols) - 0.7)
            ax.invert_yaxis()
        else:
            df_plot = df.head(5).copy()
            df_plot["Rank"] = df_plot[col_valor].rank(ascending=False, method="min")
            labels = df_plot[col_label].astype(str).tolist()
            ranks = df_plot["Rank"].tolist()
            y_pos = np.arange(len(labels))

            ax.plot(ranks, y_pos, "s-", color="#0284C7", linewidth=2, markersize=8)
            for x, y, lbl in zip(ranks, y_pos, labels):
                ax.text(x, y, f" {int(x)}º - {lbl[:15]}", ha="left", va="center", fontsize=7.5, fontweight="bold")

            ax.set_yticks([])
            ax.invert_xaxis()

        ax.spines[:].set_visible(False)
        ax.yaxis.grid(True, linestyle="--", alpha=0.5, color="#E2E8F0")

        plt.subplots_adjust(left=0.22, right=0.92, top=0.90, bottom=0.18)
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf

    @staticmethod
    def gerar_grafico_waffle(df: pd.DataFrame, col_label: str, col_valor: str) -> io.BytesIO:
        fig, ax = plt.subplots(figsize=(6.8, 2.2), dpi=300)

        df_plot = df.head(5).copy()
        total_val = df_plot[col_valor].sum()

        if total_val > 0:
            proporcoes = [int(round((v / total_val) * 100)) for v in df_plot[col_valor]]
            diff = 100 - sum(proporcoes)
            if proporcoes:
                proporcoes[0] += diff
        else:
            proporcoes = [100]

        waffle_matrix = np.zeros((10, 10))
        idx = 0
        for cat_idx, count in enumerate(proporcoes):
            for _ in range(count):
                if idx < 100:
                    r, c = divmod(idx, 10)
                    waffle_matrix[r, c] = cat_idx
                    idx += 1

        cmap = matplotlib.colors.ListedColormap(["#0284C7", "#0F172A", "#64748B", "#38BDF8", "#CBD5E1"][:len(proporcoes)])
        ax.imshow(waffle_matrix, cmap=cmap, aspect="equal")

        ax.set_xticks(np.arange(-0.5, 10, 1), minor=True)
        ax.set_yticks(np.arange(-0.5, 10, 1), minor=True)
        ax.grid(which="minor", color="white", linestyle="-", linewidth=1.5)
        ax.tick_params(which="minor", size=0)

        ax.set_xticks([])
        ax.set_yticks([])
        ax.spines[:].set_visible(False)

        labels = [str(x)[:20] for x in df_plot[col_label].tolist()]
        legend_patches = [
            matplotlib.patches.Patch(color=cmap(i), label=f"{labels[i]} ({proporcoes[i]}%)")
            for i in range(len(proporcoes))
        ]
        ax.legend(handles=legend_patches, loc="center left", bbox_to_anchor=(1.05, 0.5), frameon=False, fontsize=7.5)

        plt.subplots_adjust(left=0.05, right=0.65, top=0.95, bottom=0.05)
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf

    @staticmethod
    def gerar_grafico_area(df: pd.DataFrame, col_label: str, col_valor: str) -> io.BytesIO:
        plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
        fig, ax = plt.subplots(figsize=(6.8, 2.2), dpi=300)

        df_plot = df.head(10).copy()
        labels = [str(x)[:18] for x in df_plot[col_label].tolist()]
        valores = [float(x) for x in df_plot[col_valor].tolist()]
        x_pos = np.arange(len(labels))

        ax.fill_between(x_pos, valores, color="#0284C7", alpha=0.35, zorder=2)
        ax.plot(x_pos, valores, color="#0284C7", linewidth=2.2, marker="o", markersize=5, zorder=3)

        max_val = max(valores) if valores and max(valores) > 0 else 1.0
        for x, v in zip(x_pos, valores):
            val_txt = f"{v:,.0f}".replace(",", ".")
            ax.text(x, v + (max_val * 0.03), val_txt, ha="center", va="bottom", fontsize=6.5, fontweight="bold", color="#0F172A")

        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels, rotation=15, ha="right", fontsize=7, fontweight="bold", color="#1E293B")
        ax.set_ylim(0, max_val * 1.22)
        ax.spines[:].set_visible(False)
        ax.yaxis.grid(True, linestyle="--", alpha=0.5, color="#E2E8F0")
        ax.xaxis.grid(False)

        plt.subplots_adjust(left=0.08, right=0.95, top=0.88, bottom=0.25)
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf


class CandidateRepository:
    """Repositório de inteligência eleitoral e dados cadastrais no Lakehouse."""

    def __init__(self, db_conn: DatabaseConnection) -> None:
        self.db_conn = db_conn

    def obter_anos_disponiveis(self) -> List[str]:
        anos_encontrados = set()
        try:
            con = self.db_conn.obter_conexao()
            tables_df = con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).df()
            con.close()

            for tbl in tables_df["table_name"].tolist():
                matches = re.findall(r"(19\d\d|20\d\d)", tbl)
                for m in matches:
                    anos_encontrados.add(m)
        except Exception:
            pass

        locais_busca = [Path("./data"), Path("./lakehouse_eleitoral"), Path(".")]
        for local in locais_busca:
            if local.exists():
                for p in local.glob("**/*"):
                    if p.is_dir():
                        matches = re.findall(r"/(19\d\d|20\d\d)(?:/|$)", p.as_posix())
                        for m in matches:
                            anos_encontrados.add(m)

        if not anos_encontrados:
            raise RuntimeError("Nenhum diretório ou tabela de eleição foi localizado na base de dados do Lakehouse.")

        return sorted(list(anos_encontrados), key=lambda x: int(x))

    def resolver_ano(self, ano_solicitado: Optional[Union[int, str]] = None, ano_padrao: Optional[str] = None) -> str:
        if ano_solicitado is not None:
            return str(ano_solicitado).strip()
        if ano_padrao is not None:
            return str(ano_padrao).strip()
        anos = self.obter_anos_disponiveis()
        return anos[-1]

    def obter_nome_tabela(self, con, prefixo_tabela: str, ano: str, uf_default: str = "rj") -> str:
        try:
            tables_df = con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).df()
            tabelas = [t.lower() for t in tables_df["table_name"].tolist()]

            padrao_estrito = f"{prefixo_tabela}_{ano}_{uf_default}".lower()
            if padrao_estrito in tabelas:
                return padrao_estrito

            for t in tabelas:
                if t.startswith(f"{prefixo_tabela}_") and ano in t:
                    return t
        except Exception:
            pass
        return f"{prefixo_tabela}_{ano}_{uf_default}"

    def buscar_dados_candidato(
        self,
        nome_candidato: str,
        ano: Optional[Union[int, str]] = None,
        municipio: Optional[str] = None
    ) -> Optional[Dict]:
        ano_alvo = self.resolver_ano(ano)
        con = self.db_conn.obter_conexao()

        tbl_cand = self.obter_nome_tabela(con, "consulta_cand", ano_alvo)
        tbl_comp = self.obter_nome_tabela(con, "consulta_cand_complementar", ano_alvo)
        tbl_bens = self.obter_nome_tabela(con, "bem_candidato", ano_alvo)

        nome_esc = str(nome_candidato).strip().replace("'", "''")

        filtro_mun_sql = ""
        if municipio and str(municipio).strip():
            mun_esc = str(municipio).strip().replace("'", "''")
            filtro_mun_sql = f"AND strip_accents(UPPER(CAST(c.nome_ue AS VARCHAR))) LIKE strip_accents(UPPER('%{mun_esc}%'))"

        query_sql = f"""
        SELECT 
            c.id_candidato,
            c.cpf_candidato,
            c.nome_candidato,
            c.nome_urna_candidato,
            c.numero_candidato,
            c.numero_partido,
            c.sigla_partido,
            c.nome_partido,
            c.nome_ue,
            COALESCE(c.nome_coligacao, c.sigla_partido) AS nome_coligacao,
            c.descricao_cargo,
            c.descricao_grau_instrucao,
            c.descricao_ocupacao,
            c.data_nascimento,
            c.uf_nascimento,
            c.descricao_estado_civil,
            c.descricao_genero,
            c.descricao_cor_raca,
            COALESCE(cc.idade_data_posse, 0) AS idade_data_posse,
            COALESCE(cc.nome_municipio_nascimento, c.uf_nascimento) AS municipio_nascimento,
            COALESCE(SUM(b.valor_bem), 0) AS total_bens
        FROM {tbl_cand} c
        LEFT JOIN {tbl_comp} cc 
            ON CAST(c.id_candidato AS VARCHAR) = CAST(cc.id_candidato AS VARCHAR)
        LEFT JOIN {tbl_bens} b 
            ON CAST(c.id_candidato AS VARCHAR) = CAST(b.id_candidato AS VARCHAR)
        WHERE (strip_accents(UPPER(CAST(c.nome_urna_candidato AS VARCHAR))) LIKE strip_accents(UPPER('%{nome_esc}%'))
           OR strip_accents(UPPER(CAST(c.nome_candidato AS VARCHAR))) LIKE strip_accents(UPPER('%{nome_esc}%')))
           {filtro_mun_sql}
        GROUP BY 
            c.id_candidato, c.cpf_candidato, c.nome_candidato, c.nome_urna_candidato, c.numero_candidato, c.numero_partido,
            c.sigla_partido, c.nome_partido, c.nome_ue, c.nome_coligacao, c.descricao_cargo,
            c.descricao_grau_instrucao, c.descricao_ocupacao, c.data_nascimento,
            c.uf_nascimento, c.descricao_estado_civil, c.descricao_genero,
            c.descricao_cor_raca, cc.idade_data_posse, cc.nome_municipio_nascimento
        ORDER BY c.nome_urna_candidato, c.nome_ue
        """
        df_res = self.db_conn.executar_consulta(query_sql)
        con.close()

        if df_res.empty:
            return None

        if len(df_res) == 1:
            dados = df_res.iloc[0].to_dict()
            dados["ano_eleicao_consultado"] = ano_alvo
            return dados

        print(f"\n[DESAMBIGUAÇÃO] Foram encontrados {len(df_res)} candidatos para a busca '{nome_candidato}':\n")
        print(f"{'#':<4} | {'NOME DE URNA':<22} | {'CARGO':<15} | {'MUNICÍPIO (UE)':<20} | {'PARTIDO':<10}")
        print("-" * 80)

        for idx, row in df_res.iterrows():
            print(f"{idx + 1:<4} | {str(row['nome_urna_candidato']):<22} | {str(row['descricao_cargo']):<15} | {str(row['nome_ue']):<20} | {str(row['sigla_partido']):<10}")
        
        print("-" * 80)

        while True:
            try:
                opcao = input(f"Selecione o número do candidato desejado (1 a {len(df_res)}): ").strip()
                idx_sel = int(opcao) - 1
                if 0 <= idx_sel < len(df_res):
                    dados = df_res.iloc[idx_sel].to_dict()
                    dados["ano_eleicao_consultado"] = ano_alvo
                    return dados
                print(f"Opção inválida. Digite um número entre 1 e {len(df_res)}.")
            except (ValueError, KeyboardInterrupt):
                print("Entrada inválida. Digite o número correspondente à lista.")

    def calcular_benchmarks_cpv_municipio(
        self, ano: str, cargo: str, municipio: str, sigla_partido: Optional[str] = None
    ) -> Dict:
        """Calcula os benchmarks econométricos de CPV no município: Líder Geral de Votos e Líder do Partido."""
        con = self.db_conn.obter_conexao()
        tbl_vot = self.obter_nome_tabela(con, "votacao_candidato_munzona", ano)
        tbl_desp = self.obter_nome_tabela(con, "despesas_contratadas_candidatos", ano)

        cargo_esc = str(cargo or "VEREADOR").replace("'", "''")
        mun_esc = str(municipio or "").replace("'", "''")
        partido_esc = str(sigla_partido or "").replace("'", "''")

        q_metricas = f"""
        WITH base_votos AS (
            SELECT 
                COALESCE(CAST(id_candidato AS VARCHAR), CAST(numero_candidato AS VARCHAR)) AS cand_key,
                FIRST(CAST(id_candidato AS VARCHAR)) AS id_candidato,
                FIRST(CAST(numero_candidato AS VARCHAR)) AS numero_candidato,
                FIRST(CAST(nome_candidato AS VARCHAR)) AS nome_candidato,
                FIRST(CAST(nome_urna_candidato AS VARCHAR)) AS nome_urna_candidato,
                FIRST(CAST(sigla_partido AS VARCHAR)) AS sigla_partido,
                COALESCE(SUM(votos_nominais_validos), COALESCE(SUM(votos_nominais), 0)) AS total_votos
            FROM {tbl_vot}
            WHERE strip_accents(UPPER(COALESCE(CAST(nome_municipio AS VARCHAR), CAST(nome_ue AS VARCHAR), ''))) = strip_accents(UPPER('{mun_esc}'))
              AND strip_accents(UPPER(CAST(descricao_cargo AS VARCHAR))) = strip_accents(UPPER('{cargo_esc}'))
            GROUP BY cand_key
            HAVING total_votos > 0
        ),
        base_despesas AS (
            SELECT 
                COALESCE(CAST(id_candidato AS VARCHAR), CAST(numero_candidato AS VARCHAR)) AS cand_key,
                COALESCE(SUM(valor_despesa_contratada), 0.0) AS total_despesa
            FROM {tbl_desp}
            WHERE COALESCE(CAST(id_candidato AS VARCHAR), CAST(numero_candidato AS VARCHAR)) IN (
                SELECT cand_key FROM base_votos
            )
            GROUP BY cand_key
        )
        SELECT 
            v.id_candidato,
            v.numero_candidato,
            v.nome_candidato,
            v.nome_urna_candidato,
            v.sigla_partido,
            v.total_votos,
            COALESCE(d.total_despesa, 0.0) AS total_despesa,
            CASE 
                WHEN v.total_votos > 0 THEN (COALESCE(d.total_despesa, 0.0) / v.total_votos)
                ELSE 0.0 
            END AS cpv
        FROM base_votos v
        LEFT JOIN base_despesas d ON v.cand_key = d.cand_key
        """

        df_cand = self.db_conn.executar_consulta(q_metricas)
        con.close()

        def _item_vazio(rotulo_padrao="N/A"):
            return {
                "nome_urna": rotulo_padrao,
                "partido": rotulo_padrao,
                "votos": 0,
                "despesa": 0.0,
                "cpv": 0.0
            }

        if df_cand is None or df_cand.empty:
            return {
                "lider_geral": _item_vazio(),
                "lider_partido": _item_vazio(partido_esc or "N/A")
            }

        df_lider_geral = df_cand.sort_values(by="total_votos", ascending=False)
        row_lider_geral = df_lider_geral.iloc[0]
        lider_geral_info = {
            "nome_urna": str(row_lider_geral.get("nome_urna_candidato", "N/A")),
            "partido": str(row_lider_geral.get("sigla_partido", "N/A")),
            "votos": int(row_lider_geral.get("total_votos", 0)),
            "despesa": float(row_lider_geral.get("total_despesa", 0.0)),
            "cpv": float(row_lider_geral.get("cpv", 0.0))
        }

        if partido_esc:
            df_partido = df_cand[
                df_cand["sigla_partido"].astype(str).str.strip().str.upper() == partido_esc.strip().upper()
            ]
        else:
            df_partido = pd.DataFrame()

        if not df_partido.empty:
            df_lider_partido = df_partido.sort_values(by="total_votos", ascending=False)
            row_lider_partido = df_lider_partido.iloc[0]
            lider_partido_info = {
                "nome_urna": str(row_lider_partido.get("nome_urna_candidato", "N/A")),
                "partido": str(row_lider_partido.get("sigla_partido", "N/A")),
                "votos": int(row_lider_partido.get("total_votos", 0)),
                "despesa": float(row_lider_partido.get("total_despesa", 0.0)),
                "cpv": float(row_lider_partido.get("cpv", 0.0))
            }
        else:
            lider_partido_info = _item_vazio(partido_esc or "N/A")

        return {
            "lider_geral": lider_geral_info,
            "lider_partido": lider_partido_info
        }

    def calcular_kpis_financeiros_cpv(
        self,
        id_candidato: str,
        cpf_candidato: Optional[str],
        numero_candidato: Optional[str],
        ano: str,
        nome_candidato: Optional[str] = None,
        nome_urna_candidato: Optional[str] = None,
        cargo: Optional[str] = None,
        municipio: Optional[str] = None,
        sigla_partido: Optional[str] = None
    ) -> Dict:
        """Calcula os KPIs dos Blocos A, B e C incluindo os benchmarks econométricos do Líder Geral e do Partido."""
        con = self.db_conn.obter_conexao()
        tbl_vot = self.obter_nome_tabela(con, "votacao_candidato_munzona", ano)
        tbl_desp_cont = self.obter_nome_tabela(con, "despesas_contratadas_candidatos", ano)
        tbl_perf = self.obter_nome_tabela(con, "perfil_eleitorado", ano)

        filtro_vot = construir_filtro_candidato_sql(
            id_candidato, cpf_candidato, numero_candidato, municipio, nome_urna_candidato, nome_candidato, incluir_cpf=False
        )

        filtro_fin = construir_filtro_candidato_sql(
            id_candidato, cpf_candidato, numero_candidato, municipio, nome_urna_candidato, nome_candidato, incluir_cpf=True
        )

        if not sigla_partido and municipio:
            q_partido = f"SELECT FIRST(CAST(sigla_partido AS VARCHAR)) AS sigla_partido FROM {tbl_vot} WHERE {filtro_vot}"
            df_part = self.db_conn.executar_consulta(q_partido)
            if df_part is not None and not df_part.empty and df_part.iloc[0]["sigla_partido"]:
                sigla_partido = str(df_part.iloc[0]["sigla_partido"])

        q_votos = f"""
        SELECT COALESCE(SUM(votos_nominais_validos), COALESCE(SUM(votos_nominais), 0)) AS votos_totais
        FROM {tbl_vot}
        WHERE {filtro_vot}
        """
        df_votos = self.db_conn.executar_consulta(q_votos)
        votos_totais = int(df_votos.iloc[0]["votos_totais"]) if not df_votos.empty else 0

        cargo_esc = str(cargo or "VEREADOR").replace("'", "''")
        mun_esc = str(municipio or "").replace("'", "''")

        q_votos_mun = f"""
        SELECT COALESCE(SUM(votos_nominais_validos), COALESCE(SUM(votos_nominais), 0)) AS votos_validos_mun
        FROM {tbl_vot}
        WHERE strip_accents(UPPER(COALESCE(CAST(nome_municipio AS VARCHAR), CAST(nome_ue AS VARCHAR), ''))) = strip_accents(UPPER('{mun_esc}'))
          AND strip_accents(UPPER(CAST(descricao_cargo AS VARCHAR))) = strip_accents(UPPER('{cargo_esc}'))
        """
        df_votos_mun = self.db_conn.executar_consulta(q_votos_mun)
        votos_validos_mun = int(df_votos_mun.iloc[0]["votos_validos_mun"]) if not df_votos_mun.empty else 0

        pct_representatividade = (votos_totais / votos_validos_mun * 100) if votos_validos_mun > 0 else 0.0

        q_zonas = f"""
        SELECT 
            numero_zona,
            COALESCE(nome_municipio, nome_ue) AS nome_municipio,
            COALESCE(SUM(votos_nominais_validos), COALESCE(SUM(votos_nominais), 0)) AS votos_zona
        FROM {tbl_vot}
        WHERE {filtro_vot}
        GROUP BY numero_zona, COALESCE(nome_municipio, nome_ue)
        HAVING votos_zona > 0
        ORDER BY votos_zona DESC
        """
        df_zonas = self.db_conn.executar_consulta(q_zonas)

        if not df_zonas.empty:
            top_row = df_zonas.iloc[0]
            votos_top = int(top_row["votos_zona"])
            num_top_zona = str(top_row["numero_zona"])
            mun_top = str(top_row["nome_municipio"]).title()
            pct_votos_top = (votos_top / votos_totais * 100) if votos_totais > 0 else 0.0

            reduto_consolidado = {
                "zona_num": num_top_zona,
                "votos": votos_top,
                "pct_candidato": pct_votos_top,
                "municipio": mun_top
            }
        else:
            reduto_consolidado = {
                "zona_num": "N/A",
                "votos": 0,
                "pct_candidato": 0.0,
                "municipio": mun_esc.title()
            }

        q_expansao = f"""
        WITH base_aptos AS (
            SELECT 
                CAST(numero_zona AS VARCHAR) AS numero_zona,
                strip_accents(UPPER(CAST(nome_municipio AS VARCHAR))) AS mun_clean,
                COALESCE(SUM(quantidade_eleitores), 0) AS total_aptos
            FROM {tbl_perf}
            WHERE strip_accents(UPPER(CAST(nome_municipio AS VARCHAR))) = strip_accents(UPPER('{mun_esc}'))
            GROUP BY 1, 2
        ),
        base_votacao AS (
            SELECT 
                CAST(numero_zona AS VARCHAR) AS numero_zona,
                strip_accents(UPPER(CAST(COALESCE(nome_municipio, nome_ue) AS VARCHAR))) AS mun_clean,
                COALESCE(SUM(votos_nominais), 0) AS total_comparecimento,
                COALESCE(SUM(CASE 
                    WHEN strip_accents(UPPER(CAST(nome_candidato AS VARCHAR))) LIKE '%BRANCO%' 
                      OR strip_accents(UPPER(CAST(nome_urna_candidato AS VARCHAR))) LIKE '%BRANCO%' 
                      OR CAST(numero_candidato AS VARCHAR) IN ('95', '95000') 
                    THEN votos_nominais ELSE 0 
                END), 0) AS votos_brancos
            FROM {tbl_vot}
            WHERE strip_accents(UPPER(CAST(COALESCE(nome_municipio, nome_ue) AS VARCHAR))) = strip_accents(UPPER('{mun_esc}'))
              AND strip_accents(UPPER(CAST(descricao_cargo AS VARCHAR))) = strip_accents(UPPER('{cargo_esc}'))
            GROUP BY 1, 2
        )
        SELECT 
            a.numero_zona,
            '{mun_esc}' AS nome_municipio,
            CAST(
                GREATEST(0, (a.total_aptos - COALESCE(v.total_comparecimento, 0))) + COALESCE(v.votos_brancos, 0)
            AS BIGINT) AS eleitores_ausentes_mais_brancos
        FROM base_aptos a
        LEFT JOIN base_votacao v ON a.numero_zona = v.numero_zona
        ORDER BY eleitores_ausentes_mais_brancos DESC
        LIMIT 1
        """
        df_exp = self.db_conn.executar_consulta(q_expansao)
        if not df_exp.empty:
            exp_row = df_exp.iloc[0]
            fronteira_expansao = {
                "zona_num": str(exp_row["numero_zona"]),
                "eleitores_aptos": int(exp_row["eleitores_ausentes_mais_brancos"]),
                "municipio": str(exp_row["nome_municipio"]).title()
            }
        else:
            fronteira_expansao = {
                "zona_num": "N/A",
                "eleitores_aptos": 0,
                "municipio": mun_esc.title()
            }

        q_desp_e_pilares = f"""
        WITH base_despesas AS (
            SELECT 
                valor_despesa_contratada,
                strip_accents(UPPER(
                    COALESCE(CAST(descricao_tipo_fornecedor AS VARCHAR), '') || ' ' ||
                    COALESCE(CAST(descricao_cnae_fornecedor AS VARCHAR), '') || ' ' ||
                    COALESCE(CAST(descricao_despesa AS VARCHAR), '') || ' ' ||
                    COALESCE(CAST(descricao_origem_despesa AS VARCHAR), '') || ' ' ||
                    COALESCE(CAST(nome_fornecedor AS VARCHAR), '') || ' ' ||
                    COALESCE(CAST(nome_fornecedor_rfb AS VARCHAR), '')
                )) AS txt_busca
            FROM {tbl_desp_cont}
            WHERE {filtro_fin}
        )
        SELECT 
            COALESCE(SUM(valor_despesa_contratada), 0.0) AS despesa_total,

            COALESCE(SUM(CASE WHEN 
                txt_busca LIKE '%IMPULSIONA%' 
                OR txt_busca LIKE '%INTERNET%' 
                OR txt_busca LIKE '%REDES%' 
                OR txt_busca LIKE '%REDE SOCIAL%'
                OR txt_busca LIKE '%MIDIA DIGITAL%' 
                OR txt_busca LIKE '%MEDIA DIGITAL%'
                OR txt_busca LIKE '%TRAFEGO%' 
                OR txt_busca LIKE '%DIGITAL%'
                OR txt_busca LIKE '%FACEBOOK%'
                OR txt_busca LIKE '%META PLATFORMS%'
                OR txt_busca LIKE '%GOOGLE%'
                OR txt_busca LIKE '%BYTEDANCE%'
                OR txt_busca LIKE '%TIKTOK%'
                OR txt_busca LIKE '%INSTAGRAM%'
                OR txt_busca LIKE '%KWAI%'
                OR txt_busca LIKE '%WEBSITE%'
                OR txt_busca LIKE '%PROVEDOR%'
            THEN valor_despesa_contratada ELSE 0.0 END), 0.0) AS val_pilar_a,

            COALESCE(SUM(CASE WHEN 
                NOT (
                    txt_busca LIKE '%IMPULSIONA%' 
                    OR txt_busca LIKE '%INTERNET%' 
                    OR txt_busca LIKE '%REDES%' 
                    OR txt_busca LIKE '%REDE SOCIAL%'
                    OR txt_busca LIKE '%MIDIA DIGITAL%' 
                    OR txt_busca LIKE '%MEDIA DIGITAL%'
                    OR txt_busca LIKE '%TRAFEGO%' 
                    OR txt_busca LIKE '%DIGITAL%'
                    OR txt_busca LIKE '%FACEBOOK%'
                    OR txt_busca LIKE '%META PLATFORMS%'
                    OR txt_busca LIKE '%GOOGLE%'
                    OR txt_busca LIKE '%BYTEDANCE%'
                    OR txt_busca LIKE '%TIKTOK%'
                    OR txt_busca LIKE '%INSTAGRAM%'
                    OR txt_busca LIKE '%KWAI%'
                    OR txt_busca LIKE '%WEBSITE%'
                    OR txt_busca LIKE '%PROVEDOR%'
                ) AND NOT (
                    txt_busca LIKE '%ADVOGAD%'
                    OR txt_busca LIKE '%ADVOCACIA%'
                    OR txt_busca LIKE '%JURIDIC%'
                    OR txt_busca LIKE '%HONORARIO%'
                    OR txt_busca LIKE '%CONTAB%'
                    OR txt_busca LIKE '%CONTADOR%'
                    OR txt_busca LIKE '%ASSESSORIA JURIDICA%'
                    OR txt_busca LIKE '%SERVICOS JURIDICOS%'
                    OR txt_busca LIKE '%6911%' -- CNAE Atividades Advocatícias
                    OR txt_busca LIKE '%6920%' -- CNAE Contabilidade
                ) AND (
                    txt_busca LIKE '%PESSOA FISICA%'
                    OR txt_busca LIKE '%PESSOAL%'
                    OR txt_busca LIKE '%MILITAN%'
                    OR txt_busca LIKE '%CABO ELEITORAL%'
                    OR txt_busca LIKE '%MOBILIZA%'
                    OR txt_busca LIKE '%EVENTO%'
                    OR txt_busca LIKE '%CARRO DE SOM%'
                    OR txt_busca LIKE '%PANFLETA%'
                    OR txt_busca LIKE '%MAO DE OBRA%'
                    OR txt_busca LIKE '%AGENCIAMENTO%'
                    OR txt_busca LIKE '%RUA%'
                )
            THEN valor_despesa_contratada ELSE 0.0 END), 0.0) AS val_pilar_b,

            COALESCE(SUM(CASE WHEN 
                NOT (
                    txt_busca LIKE '%IMPULSIONA%' 
                    OR txt_busca LIKE '%INTERNET%' 
                    OR txt_busca LIKE '%REDES%' 
                    OR txt_busca LIKE '%REDE SOCIAL%'
                    OR txt_busca LIKE '%MIDIA DIGITAL%' 
                    OR txt_busca LIKE '%MEDIA DIGITAL%'
                    OR txt_busca LIKE '%TRAFEGO%' 
                    OR txt_busca LIKE '%DIGITAL%'
                    OR txt_busca LIKE '%FACEBOOK%'
                    OR txt_busca LIKE '%META PLATFORMS%'
                    OR txt_busca LIKE '%GOOGLE%'
                    OR txt_busca LIKE '%BYTEDANCE%'
                    OR txt_busca LIKE '%TIKTOK%'
                    OR txt_busca LIKE '%INSTAGRAM%'
                    OR txt_busca LIKE '%KWAI%'
                    OR txt_busca LIKE '%WEBSITE%'
                    OR txt_busca LIKE '%PROVEDOR%'
                ) AND NOT (
                    txt_busca LIKE '%PESSOA FISICA%'
                    OR txt_busca LIKE '%PESSOAL%'
                    OR txt_busca LIKE '%MILITAN%'
                    OR txt_busca LIKE '%CABO ELEITORAL%'
                    OR txt_busca LIKE '%MOBILIZA%'
                    OR txt_busca LIKE '%EVENTO%'
                    OR txt_busca LIKE '%CARRO DE SOM%'
                    OR txt_busca LIKE '%PANFLETA%'
                    OR txt_busca LIKE '%MAO DE OBRA%'
                    OR txt_busca LIKE '%AGENCIAMENTO%'
                    OR txt_busca LIKE '%RUA%'
                ) AND (
                    txt_busca LIKE '%IMPRES%'
                    OR txt_busca LIKE '%GRAFIC%'
                    OR txt_busca LIKE '%ADESIVO%'
                    OR txt_busca LIKE '%BANNER%'
                    OR txt_busca LIKE '%FOLHETO%'
                    OR txt_busca LIKE '%JORNAL%'
                    OR txt_busca LIKE '%PANFLETO%'
                    OR txt_busca LIKE '%PRODUTORA%'
                    OR txt_busca LIKE '%PRODUCAO%'
                    OR txt_busca LIKE '%CINEMA%'
                    OR txt_busca LIKE '%VIDEO%'
                    OR txt_busca LIKE '%AUDIO%'
                    OR txt_busca LIKE '%RADIO%'
                    OR txt_busca LIKE '%TELEVISAO%'
                    OR txt_busca LIKE '%EMBALAGEM%'
                    OR txt_busca LIKE '%PAPEL%'
                    OR txt_busca LIKE '%PUBLICIDADE%'
                    OR txt_busca LIKE '%TERCEIRO%'
                )
            THEN valor_despesa_contratada ELSE 0.0 END), 0.0) AS val_pilar_c
        FROM base_despesas
        """

        df_fin = self.db_conn.executar_consulta(q_desp_e_pilares)

        if not df_fin.empty:
            despesa_total = float(df_fin.iloc[0]["despesa_total"])
            val_pilar_a = float(df_fin.iloc[0]["val_pilar_a"])
            val_pilar_b = float(df_fin.iloc[0]["val_pilar_b"])
            val_pilar_c = float(df_fin.iloc[0]["val_pilar_c"])
            val_pilar_d = max(0.0, despesa_total - (val_pilar_a + val_pilar_b + val_pilar_c))
        else:
            despesa_total = 0.0
            val_pilar_a = 0.0
            val_pilar_b = 0.0
            val_pilar_c = 0.0
            val_pilar_d = 0.0

        cpv_global = (despesa_total / votos_totais) if votos_totais > 0 else 0.0

        pilares = {
            "Pilar A (Mídia Digital & Tráfego)": val_pilar_a,
            "Pilar B (Militância & Rua)": val_pilar_b,
            "Pilar C (Produtoras & Impressos)": val_pilar_c,
            "Pilar D (Operacional & Logística)": val_pilar_d,
        }

        q_coorte = f"""
        SELECT 
            CASE 
                WHEN LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%16%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%17%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%18%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%19%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%20%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%21%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%22%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%23%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%24%' THEN '1. Jovem (16-24)'
                WHEN LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%25%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%26%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%27%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%28%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%29%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%30%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%31%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%32%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%33%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%34%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%35%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%36%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%37%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%38%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%39%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%40%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%41%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%42%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%43%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%44%' THEN '2. Adulto Jovem (25-44)'
                WHEN LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%45%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%46%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%47%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%48%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%49%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%50%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%51%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%52%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%53%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%54%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%55%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%56%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%57%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%58%' OR LOWER(CAST(descricao_faixa_etaria AS VARCHAR)) LIKE '%59%' THEN '3. Adulto Maduro (45-59)'
                ELSE '4. Sênior (60+)'
            END AS coorte_ibge,
            COALESCE(SUM(quantidade_eleitores), 0) AS total_eleitores
        FROM {tbl_perf}
        WHERE strip_accents(UPPER(CAST(nome_municipio AS VARCHAR))) = strip_accents(UPPER('{mun_esc}'))
        GROUP BY 1
        ORDER BY total_eleitores DESC
        LIMIT 1
        """
        df_coorte = self.db_conn.executar_consulta(q_coorte)
        if df_coorte.empty or df_coorte.iloc[0]["total_eleitores"] == 0:
            raise ValueError(f"Dados demográficos de faixa etária ausentes para o município de '{municipio}'.")
        coorte_predominante = str(df_coorte.iloc[0]["coorte_ibge"])

        q_esc = f"""
        SELECT 
            CASE 
                WHEN CAST(codigo_grau_escolaridade AS VARCHAR) IN ('1') OR CAST(descricao_grau_escolaridade AS VARCHAR) IN ('1') THEN 'Analfabeto'
                WHEN CAST(codigo_grau_escolaridade AS VARCHAR) IN ('2') OR CAST(descricao_grau_escolaridade AS VARCHAR) IN ('2') THEN 'Lê e Escreve'
                WHEN CAST(codigo_grau_escolaridade AS VARCHAR) IN ('3') OR CAST(descricao_grau_escolaridade AS VARCHAR) IN ('3') THEN 'Ensino Fundamental Incompleto'
                WHEN CAST(codigo_grau_escolaridade AS VARCHAR) IN ('4') OR CAST(descricao_grau_escolaridade AS VARCHAR) IN ('4') THEN 'Ensino Fundamental Completo'
                WHEN CAST(codigo_grau_escolaridade AS VARCHAR) IN ('5') OR CAST(descricao_grau_escolaridade AS VARCHAR) IN ('5') THEN 'Ensino Médio Incompleto'
                WHEN CAST(codigo_grau_escolaridade AS VARCHAR) IN ('6') OR CAST(descricao_grau_escolaridade AS VARCHAR) IN ('6') THEN 'Ensino Médio Completo'
                WHEN CAST(codigo_grau_escolaridade AS VARCHAR) IN ('7') OR CAST(descricao_grau_escolaridade AS VARCHAR) IN ('7') THEN 'Superior Incompleto'
                WHEN CAST(codigo_grau_escolaridade AS VARCHAR) IN ('8') OR CAST(descricao_grau_escolaridade AS VARCHAR) IN ('8') THEN 'Superior Completo'
                ELSE 'Outros / Não Informado'
            END AS grau_esc,
            COALESCE(SUM(quantidade_eleitores), 0) AS total_eleitores
        FROM {tbl_perf}
        WHERE strip_accents(UPPER(CAST(nome_municipio AS VARCHAR))) = strip_accents(UPPER('{mun_esc}'))
        GROUP BY 1
        ORDER BY total_eleitores DESC
        LIMIT 1
        """
        df_esc = self.db_conn.executar_consulta(q_esc)
        if df_esc.empty or df_esc.iloc[0]["total_eleitores"] == 0:
            raise ValueError(f"Dados demográficos de escolaridade ausentes para o município de '{municipio}'.")
        escolaridade_predominante = str(df_esc.iloc[0]["grau_esc"])

        con.close()

        benchmarks_cpv = self.calcular_benchmarks_cpv_municipio(
            ano, cargo or "VEREADOR", municipio or "", sigla_partido
        )

        return {
            "votos_totais": votos_totais,
            "votos_validos_mun": votos_validos_mun,
            "pct_representatividade": pct_representatividade,
            "reduto_consolidado": reduto_consolidado,
            "fronteira_expansao": fronteira_expansao,
            "despesa_total": despesa_total,
            "cpv_global": cpv_global,
            "pilares": pilares,
            "coorte_predominante": coorte_predominante,
            "escolaridade_predominante": escolaridade_predominante,
            "benchmarks_cpv": benchmarks_cpv,
            "benchmark_lider": benchmarks_cpv["lider_geral"]
        }

    def localizar_foto_candidato(
        self, id_candidato: str, ano: Optional[Union[int, str]] = None, diretorio_customizado: Optional[str] = None
    ) -> Optional[Path]:
        ano_alvo = self.resolver_ano(ano)
        anos_para_buscar = [ano_alvo]

        ano_recente = self.obter_anos_disponiveis()[-1]
        if ano_recente not in anos_para_buscar:
            anos_para_buscar.append(ano_recente)

        diretorios_candidatos = []
        if diretorio_customizado:
            diretorios_candidatos.append(Path(diretorio_customizado))

        for a in anos_para_buscar:
            diretorios_candidatos.extend([
                Path(f"./data/{a}/candidato/foto_cand{a}_RJ_div"),
                Path(f"./data/{a}/candidato"),
                Path(f"./{a}/candidato/foto_cand{a}_RJ_div"),
                Path(f"./{a}/candidato"),
            ])
            for base in [Path(f"./data/{a}"), Path(f"./{a}")]:
                if base.exists():
                    for sub in base.glob("**/*"):
                        if sub.is_dir() and any(k in sub.name.lower() for k in ["foto", "cand"]):
                            diretorios_candidatos.append(sub)

        padroes = [
            f"F{id_candidato}_div.jpg",
            f"F{id_candidato}_div.jpeg",
            f"F{id_candidato}_div.png",
            f"FRJ{id_candidato}_div.jpg",
            f"*{id_candidato}*.jpg",
            f"*{id_candidato}*.jpeg",
            f"*{id_candidato}*.png",
        ]

        for dir_foto in diretorios_candidatos:
            if dir_foto.exists():
                for padrao in padroes:
                    encontrados = list(dir_foto.glob(padrao))
                    if encontrados:
                        return encontrados[0]
        return None


class ExecutivePDFGenerator:
    """Gerador C-Level de Dossiês Eleitorais em PDF com layout atômico e otimizado."""

    def __init__(
        self,
        caminho_saida_pdf: Optional[str] = None,
        diretorio_fotos: Optional[str] = None,
        ano: Optional[Union[int, str]] = None,
    ) -> None:
        self.caminho_saida_param = caminho_saida_pdf
        self.diretorio_fotos_customizado = diretorio_fotos
        self.ano_padrao = str(ano).strip() if ano is not None else None
        self.db_conn = DatabaseConnection()
        self.repo = CandidateRepository(self.db_conn)
        self.styles = getSampleStyleSheet()
        self._configurar_estilos()

    def _configurar_estilos(self) -> None:
        """Configura os estilos tipográficos executivos centralizados para relatórios C-Level."""
        self.estilo_topo_subtitulo = ParagraphStyle(
            "HeaderSubtitle",
            parent=self.styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.0,
            leading=11,
            textColor=colors.HexColor("#0284C7"),
            spaceAfter=2,
        )
        self.estilo_nome_urna = ParagraphStyle(
            "CandidateUrnName",
            parent=self.styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#0F172A"),
            spaceAfter=4,
        )
        self.estilo_secao = ParagraphStyle(
            "SectionTitle",
            parent=self.styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=10.0,
            leading=13.0,
            textColor=colors.HexColor("#0F172A"),
            spaceBefore=6,
            spaceAfter=3,
        )
        self.estilo_bloco_header = ParagraphStyle(
            "BlockHeader",
            parent=self.styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.0,
            leading=12.0,
            textColor=colors.HexColor("#0284C7"),
            spaceBefore=4,
            spaceAfter=3,
        )
        self.estilo_pergunta_box = ParagraphStyle(
            "QuestionBoxStyle",
            parent=self.styles["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#0369A1"),
        )
        self.estilo_conclusao_box = ParagraphStyle(
            "ConclusionBoxStyle",
            parent=self.styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#0F172A"),
        )

        self.estilo_kpi_titulo = ParagraphStyle(
            "KPITitle",
            parent=self.styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.0,
            leading=9.0,
            textColor=colors.HexColor("#64748B"),
        )
        self.estilo_kpi_valor = ParagraphStyle(
            "KPIValue",
            parent=self.styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.0,
            leading=12.5,
            textColor=colors.HexColor("#0F172A"),
        )
        self.estilo_kpi_subtexto = ParagraphStyle(
            "KPISubtext",
            parent=self.styles["Normal"],
            fontName="Helvetica",
            fontSize=7.0,
            leading=9.0,
            textColor=colors.HexColor("#475569"),
        )

        self.estilo_ficha_valor = ParagraphStyle(
            "ValueStyle",
            parent=self.styles["Normal"],
            fontName="Helvetica",
            fontSize=8.0,
            leading=12.0,
            textColor=colors.HexColor("#334155"),
        )
        self.estilo_celula_cabecalho = ParagraphStyle(
            "CellHeader",
            parent=self.styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=10,
            textColor=colors.white,
        )
        self.estilo_celula_corpo = ParagraphStyle(
            "CellBody",
            parent=self.styles["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#1E293B"),
        )

    def _formatar_inteiro(self, val: object) -> str:
        try:
            return f"{int(round(float(val))):,}".replace(",", ".")
        except (ValueError, TypeError):
            return "0"

    def _formatar_moeda(self, val: object) -> str:
        try:
            v = float(val)
            return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except (ValueError, TypeError):
            return "R$ 0,00"

    def _construir_quadro_perfil(self, cand: Dict, ano: Optional[Union[int, str]] = None) -> Table:
        id_cand = str(cand.get("id_candidato", ""))
        ano_cand = cand.get("ano_eleicao_consultado", ano)
        caminho_foto = self.repo.localizar_foto_candidato(
            id_cand, ano=ano_cand, diretorio_customizado=self.diretorio_fotos_customizado
        )

        if caminho_foto and caminho_foto.exists():
            img_element = Image(str(caminho_foto), width=1.1 * inch, height=1.35 * inch)
        else:
            img_element = Paragraph("<b>[Sem Foto]</b>", self.estilo_ficha_valor)

        bloco_foto = [
            img_element,
            Spacer(1, 3),
            Paragraph("<font size=7 color='#64748B'>Fonte: TSE</font>", self.estilo_ficha_valor),
        ]

        num_partido_str = str(cand.get("numero_partido", "") or "").strip()
        num_cand_str = str(cand.get("numero_candidato", "") or "").strip()
        sigla_partido_str = str(cand.get("sigla_partido", "") or "").strip()

        rotulo_partido_urna = f"{num_partido_str} / {num_cand_str} ({sigla_partido_str})" if num_partido_str else f"{num_cand_str} ({sigla_partido_str})"

        col1_text = f"""
        <b>Nome completo:</b><br/>{cand.get('nome_candidato', '')}<br/><br/>
        <b>Nº do Partido / Urna:</b><br/>{rotulo_partido_urna}<br/><br/>
        <b>Coligação:</b><br/>{cand.get('nome_coligacao', '')}<br/><br/>
        <b>Grau de instrução:</b><br/>{cand.get('descricao_grau_instrucao', '')}
        """

        idade_str = f"{cand.get('idade_data_posse', '')} ({cand.get('data_nascimento', '')})"
        col2_text = f"""
        <b>Ocupação:</b><br/>{cand.get('descricao_ocupacao', '')}<br/><br/>
        <b>Idade:</b><br/>{idade_str}<br/><br/>
        <b>Cidade de nascimento:</b><br/>{cand.get('municipio_nascimento', '')}<br/><br/>
        <b>Estado civil:</b><br/>{cand.get('descricao_estado_civil', '')}
        """

        bens_fmt = self._formatar_moeda(cand.get("total_bens", 0))
        col3_text = f"""
        <b>Identidade de gênero:</b><br/>{cand.get('descricao_genero', '')}<br/><br/>
        <b>Orientação sexual:</b><br/>Não informado<br/><br/>
        <b>Cor/Raça:</b><br/>{cand.get('descricao_cor_raca', '')}<br/><br/>
        <b>Bens declarados:</b><br/><font color='#0284C7'><b>{bens_fmt}</b></font>
        """

        p_col1 = Paragraph(col1_text, self.estilo_ficha_valor)
        p_col2 = Paragraph(col2_text, self.estilo_ficha_valor)
        p_col3 = Paragraph(col3_text, self.estilo_ficha_valor)

        tabela_quadro = Table(
            [[bloco_foto, p_col1, p_col2, p_col3]],
            colWidths=[1.2 * inch, 2.0 * inch, 2.0 * inch, 2.06 * inch],
        )
        tabela_quadro.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E2E8F0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ]
            )
        )
        return tabela_quadro

    def _construir_bloco_a_dominancia(self, kpis: Dict) -> Table:
        votos_fmt = self._formatar_inteiro(kpis.get("votos_totais", 0))
        pct_rep = kpis.get("pct_representatividade", 0.0)

        reduto = kpis.get("reduto_consolidado", {})
        red_str = f"Zona {reduto.get('zona_num', 'N/A')}"
        red_sub = f"<b>{self._formatar_inteiro(reduto.get('votos', 0))} votos</b> ({reduto.get('pct_candidato', 0.0):.1f}% do total) • {reduto.get('municipio', '')}"

        expansao = kpis.get("fronteira_expansao", {})
        exp_str = f"Zona XX" #{expansao.get('zona_num', 'N/A')}
        exp_sub = f"<b>{self._formatar_inteiro(expansao.get('eleitores_aptos', 0))} Ausentes + Brancos</b> • {expansao.get('municipio', '')}"

        card1 = [
            Paragraph("VOTOS TOTAIS & REPRESENTATIVIDADE", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<b>{votos_fmt} Votos</b>", self.estilo_kpi_valor),
            Spacer(1, 1),
            Paragraph(f"<b>{pct_rep:.2f}%</b> do Eleitorado Válido do Cargo", self.estilo_kpi_subtexto),
        ]
        card2 = [
            Paragraph("REDUTO CONSOLIDADO (MAIOR VOTAÇÃO)", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<font color='#16A34A'><b>{red_str}</b></font>", self.estilo_kpi_valor),
            Spacer(1, 1),
            Paragraph(red_sub, self.estilo_kpi_subtexto),
        ]
        card3 = [
            Paragraph("FRONTEIRA DE EXPANSÃO (OCEANO AZUL)", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<font color='#0284C7'><b>{exp_str}</b></font>", self.estilo_kpi_valor),
            Spacer(1, 1),
            Paragraph(exp_sub, self.estilo_kpi_subtexto),
        ]

        w_card = 523.27 / 3
        tabela = Table([[card1, card2, card3]], colWidths=[w_card, w_card, w_card])
        tabela.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ]
            )
        )
        return tabela

    def _construir_bloco_b_engenharia_financeira(self, kpis: Dict, ano: str, municipio: Optional[str] = None) -> KeepTogether:
        """Constrói o Bloco B com o Quadro Único Unificado de 4 Informações Lado a Lado."""
        elementos_bloco = []

        despesa_tot = float(kpis.get("despesa_total", 0.0))
        votos_totais = int(kpis.get("votos_totais", 0))
        cpv_global = float(kpis.get("cpv_global", 0.0))

        despesa_fmt = self._formatar_moeda(despesa_tot)
        cpv_fmt = self._formatar_moeda(cpv_global)
        votos_totais_fmt = self._formatar_inteiro(votos_totais)

        benchmarks = kpis.get("benchmarks_cpv", {})
        lider_geral = benchmarks.get("lider_geral", kpis.get("benchmark_lider", {}))
        lider_partido = benchmarks.get("lider_partido", {})

        cpv_lider_geral_fmt = self._formatar_moeda(lider_geral.get("cpv", 0.0))
        nome_lider_geral = str(lider_geral.get("nome_urna", "Líder")).title()
        votos_lider_geral = self._formatar_inteiro(lider_geral.get("votos", 0))

        cpv_lider_partido_fmt = self._formatar_moeda(lider_partido.get("cpv", 0.0))
        nome_lider_partido = str(lider_partido.get("nome_urna", "N/A")).title()
        partido_lider_partido = str(lider_partido.get("partido", ""))
        votos_lider_partido = self._formatar_inteiro(lider_partido.get("votos", 0))

        card_inv = [
            Paragraph("INVESTIMENTO DECLARADO", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<b>{despesa_fmt}</b>", self.estilo_kpi_valor),
            Spacer(1, 1),
            Paragraph("Despesas Contratadas", self.estilo_kpi_subtexto),
        ]

        card_cand_cpv = [
            Paragraph("CPV DO CANDIDATO ANALISADO", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<font color='#D97706'><b>{cpv_fmt} / voto</b></font>", self.estilo_kpi_valor),
            Spacer(1, 1),
            Paragraph(f"<b>Candidato do Dossiê</b> • {self._formatar_inteiro(votos_totais_fmt)} Votos", self.estilo_kpi_subtexto),
        ]

        card_lider_geral = [
            Paragraph("CPV DO LÍDER GERAL", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<font color='#16A34A'><b>{cpv_lider_geral_fmt} / voto</b></font>", self.estilo_kpi_valor),
            Spacer(1, 1),
            Paragraph(f"<b>{nome_lider_geral[:17]}</b> {votos_lider_geral} Votos", self.estilo_kpi_subtexto),
        ]

        rotulo_partido = partido_lider_partido if partido_lider_partido else "PARTIDO"
        card_lider_partido = [
            Paragraph(f"CPV DO LÍDER DO PARTIDO ({rotulo_partido})", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<font color='#0284C7'><b>{cpv_lider_partido_fmt} / voto</b></font>", self.estilo_kpi_valor),
            Spacer(1, 1),
            Paragraph(f"<b>{nome_lider_partido[:17]}</b> {votos_lider_partido} Votos", self.estilo_kpi_subtexto),
        ]

        w_card = 523.27 / 4
        t_quadro_4_cards = Table(
            [[card_inv, card_cand_cpv, card_lider_geral, card_lider_partido]],
            colWidths=[w_card, w_card, w_card, w_card]
        )
        t_quadro_4_cards.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ]
            )
        )
        elementos_bloco.append(t_quadro_4_cards)
        elementos_bloco.append(Spacer(1, 6))

        pilares = kpis.get("pilares", {})
        val_pilar_a = float(pilares.get("Pilar A (Mídia Digital & Tráfego)", 0.0))
        val_pilar_b = float(pilares.get("Pilar B (Militância & Rua)", 0.0))
        val_pilar_c = float(pilares.get("Pilar C (Produtoras & Impressos)", 0.0))
        val_pilar_d = float(pilares.get("Pilar D (Operacional & Logística)", 0.0))

        cpv_pilar_a = (val_pilar_a / votos_totais) if votos_totais > 0 else 0.0
        cpv_pilar_b = (val_pilar_b / votos_totais) if votos_totais > 0 else 0.0

        val_a_fmt = self._formatar_moeda(val_pilar_a)
        cpv_a_fmt = self._formatar_moeda(cpv_pilar_a)
        val_b_fmt = self._formatar_moeda(val_pilar_b)
        cpv_b_fmt = self._formatar_moeda(cpv_pilar_b)
        val_c_fmt = self._formatar_moeda(val_pilar_c)
        val_d_fmt = self._formatar_moeda(val_pilar_d)

        exp = kpis.get("fronteira_expansao", {})
        zona_exp = str(exp.get("zona_num", "N/A"))
        eleitores_aptos = int(exp.get("eleitores_aptos", 0))

        if eleitores_aptos > 0:
            razao_aptos = eleitores_aptos / (cpv_global + 1.0)
            ipac_val = 1.0 + math.log(max(1.0, razao_aptos))
        else:
            ipac_val = 1.0

        saturacao_sz = max(0, eleitores_aptos - votos_totais)
        razao_saturacao = (saturacao_sz / (saturacao_sz + votos_totais + 1e-5))
        fatia_dinamica_w = min(0.85, max(0.15, razao_saturacao * (ipac_val / 10.0)))
        pct_dinamico_fmt = f"{fatia_dinamica_w * 100:.1f}%"

        texto_painel = f"""
        • <b>Alocação por Pilar Estratégico:</b><br/>
        &nbsp;&nbsp;&nbsp;- <b>Pilar A (Mídias Digitais & Tráfego):</b> {val_a_fmt} ({cpv_a_fmt}/voto)<br/>
        &nbsp;&nbsp;&nbsp;- <b>Pilar B (Mobilização de Rua & Militância):</b> {val_b_fmt} ({cpv_b_fmt}/voto)<br/>
        &nbsp;&nbsp;&nbsp;- <b>Pilar C (Produtoras & Impressos):</b> {val_c_fmt}<br/>
        &nbsp;&nbsp;&nbsp;- <b>Pilar D (Logística & Operacional):</b> {val_d_fmt}<br/><br/>
        • <b>Recomendação Prescritiva:</b> A <b>Zona XX</b> detém o maior Retorno sobre Investimento (<i>Índice Prescritivo de Alocação de Capital</i> = {ipac_val:.2f}) devido à densidade de eleitores aptos que não compareceram às urnas. Recomenda-se alocar <b>{pct_dinamico_fmt} do Pilar A</b> em tráfego pago geolocalizado para esta zona, maximizando o retorno marginal.
        """                                         #{zona_exp}

        p_painel = Paragraph(texto_painel, self.estilo_conclusao_box)
        t_painel = Table([[p_painel]], colWidths=[523.27])
        t_painel.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0F9FF")),
                    ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#0284C7")),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ]
            )
        )
        elementos_bloco.append(t_painel)

        return KeepTogether(elementos_bloco)

    def _construir_bloco_c_inteligencia_demografica(self, kpis: Dict) -> KeepTogether:
        elementos_bloco = []

        if "coorte_predominante" not in kpis or "escolaridade_predominante" not in kpis:
            raise KeyError("Erro de Integridade: KPIs demográficos ausentes.")

        coorte = kpis["coorte_predominante"]
        esc = kpis["escolaridade_predominante"]

        card1 = [
            Paragraph("FAIXA ETÁRIA PREDOMINANTE NO REDUTO SEGUNDO IBGE", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<font color='#0284C7'><b>XXXXX</b></font>", self.estilo_kpi_valor), #{coorte}
            Spacer(1, 1),
            Paragraph("Maior Concentração e Peso Eleitoral", self.estilo_kpi_subtexto),
        ]
        card2 = [
            Paragraph("GRAU DE ESCOLARIDADE PREDOMINANTE", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<b>XXXXX</b>", self.estilo_kpi_valor), #{esc}
            Spacer(1, 1),
            Paragraph("Nível de Instrução e Perfil Educacional", self.estilo_kpi_subtexto),
        ]

        w_card2 = 523.27 / 2
        t_cards = Table([[card1, card2]], colWidths=[w_card2, w_card2])
        t_cards.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ]
            )
        )
        elementos_bloco.append(t_cards)
        elementos_bloco.append(Spacer(1, 6))

        return KeepTogether(elementos_bloco)

    def _construir_box_pergunta(self, pergunta: str) -> Table:
        p_box_text = f"<b>PERGUNTA ESTRATÉGICA FORMULADA:</b><br/>“{pergunta}”"
        t_pergunta = Table([[Paragraph(p_box_text, self.estilo_pergunta_box)]], colWidths=[523.27])
        t_pergunta.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0F9FF")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#0284C7")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ]
            )
        )
        return t_pergunta

    def _construir_box_conclusao(self, conclusao: str) -> Table:
        c_box_text = f"<b>■ RECOMENDAÇÃO ESTRATÉGICA DE INVESTIMENTO:</b><br/>{conclusao}"
        t_conclusao = Table([[Paragraph(c_box_text, self.estilo_conclusao_box)]], colWidths=[523.27])
        t_conclusao.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#0F172A")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ]
            )
        )
        return t_conclusao

    def gerar_pdf(
        self,
        nome_candidato: Optional[str] = None,
        analises: Optional[List[ItemAnaliseEstrategica]] = None,
        perguntas: Optional[List[str]] = None,
        queries: Optional[List[str]] = None,
        titulos: Optional[List[str]] = None,
        conclusoes_negocio: Optional[List[str]] = None,
        modelos_graficos: Optional[List[str]] = None,
        ano: Optional[Union[int, str]] = None,
        municipio: Optional[str] = None,
    ) -> Path:
        ano_resolvido = self.repo.resolver_ano(ano, self.ano_padrao)

        cand_info = (
            self.repo.buscar_dados_candidato(nome_candidato, ano=ano_resolvido, municipio=municipio)
            if nome_candidato
            else None
        )

        if cand_info:
            nome_cand_completo = str(cand_info.get("nome_candidato", nome_candidato)).strip()
            nome_urna = str(cand_info.get("nome_urna_candidato", nome_candidato)).strip()
            id_cand = str(cand_info.get("id_candidato", "")).strip()
            cpf_cand = str(cand_info.get("cpf_candidato", "")).strip()
            num_cand = str(cand_info.get("numero_candidato", "")).strip()
            municipio = str(cand_info.get("nome_ue", municipio or "")).strip().upper()
            cargo_cand = str(cand_info.get("descricao_cargo", "VEREADOR")).strip().upper()
            sigla_partido_cand = str(cand_info.get("sigla_partido", "")).strip()
        else:
            nome_cand_completo = nome_candidato or "Candidato"
            nome_urna = nome_candidato or "Relatorio"
            id_cand = ""
            cpf_cand = ""
            num_cand = ""
            municipio = str(municipio or "").strip().upper()
            cargo_cand = "VEREADOR"
            sigla_partido_cand = ""

        municipio_formatado = municipio.title() if municipio else ""

        if self.caminho_saida_param:
            caminho_final = Path(self.caminho_saida_param)
        else:
            caminho_final = Path(gerar_nome_arquivo_pdf(nome_urna))

        doc = SimpleDocTemplate(
            str(caminho_final),
            pagesize=A4,
            leftMargin=36,
            rightMargin=36,
            topMargin=30,
            bottomMargin=36,
        )

        elementos = []

        elementos.append(
            Paragraph(
                "DIRCEU - CIÊNCIA & DADOS • DOSSIÊ EXECUTIVO DE INTELIGÊNCIA ESTRATÉGICA",
                self.estilo_topo_subtitulo,
            )
        )

        if cand_info:
            nome_urna_top = nome_urna.upper()
            elementos.append(Paragraph(f"<b>{nome_urna_top}</b>", self.estilo_nome_urna))
            elementos.append(
                HRFlowable(
                    width="100%", thickness=1.5, color=colors.HexColor("#0284C7"), spaceBefore=2, spaceAfter=5
                )
            )
            elementos.append(self._construir_quadro_perfil(cand_info, ano=ano_resolvido))
            elementos.append(Spacer(1, 10))

            kpis_mestre = self.repo.calcular_kpis_financeiros_cpv(
                id_cand,
                cpf_cand,
                num_cand,
                ano_resolvido,
                nome_candidato=nome_cand_completo,
                nome_urna_candidato=nome_urna,
                cargo=cargo_cand,
                municipio=municipio,
                sigla_partido=sigla_partido_cand,
            )

            elementos.append(
                Paragraph("<b>DIAGNÓSTICO VOLUMÉTRICO & DOMINÂNCIA TERRITORIAL</b>", self.estilo_bloco_header)
            )
            elementos.append(self._construir_bloco_a_dominancia(kpis_mestre))
            elementos.append(Spacer(1, 10))

            elementos.append(
                Paragraph(
                    "<b>ENGENHARIA FINANCEIRA DE CAMPANHA & ALOCAÇÃO ESTRATÉGICA</b>", self.estilo_bloco_header
                )
            )
            elementos.append(self._construir_bloco_b_engenharia_financeira(kpis_mestre, ano_resolvido, municipio=municipio))
            elementos.append(Spacer(1, 10))

            elementos.append(
                Paragraph("<b>INTELIGÊNCIA DEMOGRÁFICA</b>", self.estilo_bloco_header)
            )
            elementos.append(self._construir_bloco_c_inteligencia_demografica(kpis_mestre))
            elementos.append(Spacer(1, 14))

        elif nome_candidato:
            elementos.append(Paragraph(f"<b>{nome_candidato.upper()}</b>", self.estilo_nome_urna))
            elementos.append(
                HRFlowable(
                    width="100%", thickness=1.5, color=colors.HexColor("#0284C7"), spaceBefore=2, spaceAfter=5
                )
            )
            elementos.append(
                Paragraph(
                    f"<i>Candidato '{nome_candidato}' não localizado na base eleitoral ({ano_resolvido}).</i>",
                    self.estilo_celula_corpo,
                )
            )
            elementos.append(Spacer(1, 12))

        lista_analises: List[ItemAnaliseEstrategica] = []

        if analises:
            lista_analises = analises
        elif queries:
            total_items = len(queries)
            for i in range(total_items):
                p_text = perguntas[i] if perguntas and i < len(perguntas) else f"Análise Estratégica #{i+1}"
                t_text = titulos[i] if titulos and i < len(titulos) else f"Resultado da Análise #{i+1}"
                q_text = queries[i]
                c_text = conclusoes_negocio[i] if conclusoes_negocio and i < len(conclusoes_negocio) else None
                m_text = modelos_graficos[i] if modelos_graficos and i < len(modelos_graficos) else "lollipop"

                p_text_fmt = p_text.format(municipio=municipio_formatado, candidato=nome_urna)
                t_text_fmt = t_text.format(municipio=municipio_formatado, candidato=nome_urna)

                lista_analises.append(
                    ItemAnaliseEstrategica(
                        pergunta=p_text_fmt,
                        titulo_grafico=t_text_fmt,
                        query_sql=q_text,
                        conclusao_negocio=c_text,
                        modelo_grafico=m_text,
                    )
                )

        if lista_analises:
            elementos.append(
                Paragraph("<b>ANÁLISES GRÁFICAS DE INTELIGÊNCIA & ESTRATÉGIA</b>", self.estilo_secao)
            )
            elementos.append(
                HRFlowable(
                    width="100%", thickness=1.0, color=colors.HexColor("#0F172A"), spaceBefore=1, spaceAfter=10
                )
            )

            con_tmp = self.db_conn.obter_conexao()
            tbl_desp_nome = self.repo.obter_nome_tabela(con_tmp, "despesas_contratadas_candidatos", ano_resolvido)
            tbl_rec_nome = self.repo.obter_nome_tabela(con_tmp, "receitas_candidatos", ano_resolvido)
            tbl_vot_nome = self.repo.obter_nome_tabela(con_tmp, "votacao_candidato_munzona", ano_resolvido)
            tbl_perf_nome = self.repo.obter_nome_tabela(con_tmp, "perfil_eleitorado", ano_resolvido)
            con_tmp.close()

            filtro_vot_sql = construir_filtro_candidato_sql(
                id_cand, cpf_cand, num_cand, municipio, nome_urna, nome_cand_completo, incluir_cpf=False
            )
            filtro_fin_sql = construir_filtro_candidato_sql(
                id_cand, cpf_cand, num_cand, municipio, nome_urna, nome_cand_completo, incluir_cpf=True
            )

            total_blocos = len(lista_analises)

            for idx, item in enumerate(lista_analises):
                sub_elementos = []

                if item.pergunta:
                    sub_elementos.append(self._construir_box_pergunta(item.pergunta))
                    sub_elementos.append(Spacer(1, 5))

                if item.titulo_grafico:
                    sub_elementos.append(Paragraph(f"<b>{item.titulo_grafico}</b>", self.estilo_secao))
                    sub_elementos.append(Spacer(1, 3))

                query_raw = item.query_sql
                filtro_usar = filtro_vot_sql if "{tabela_votacao}" in query_raw else filtro_fin_sql

                query_processada = query_raw.format(
                    ano=ano_resolvido,
                    id_candidato=id_cand,
                    nome_candidato=nome_cand_completo.replace("'", "''"),
                    nome_urna_candidato=nome_urna.replace("'", "''"),
                    municipio=municipio.replace("'", "''"),
                    filtro_candidato=filtro_usar,
                    tabela_despesas=tbl_desp_nome,
                    tabela_receitas=tbl_rec_nome,
                    tabela_votacao=tbl_vot_nome,
                    tabela_perfil=tbl_perf_nome,
                    cargo=cargo_cand.replace("'", "''")
                )

                df_res = self.db_conn.executar_consulta(query_processada)

                if df_res is None or df_res.empty:
                    sub_elementos.append(Paragraph("Nenhum registro encontrado.", self.estilo_celula_corpo))
                    sub_elementos.append(Spacer(1, 6))
                else:
                    colunas_orig = list(df_res.columns)
                    col_texto = colunas_orig[0]
                    col_num = colunas_orig[1] if len(colunas_orig) > 1 else colunas_orig[0]

                    buf_grafico = ExecutiveChartRenderer.renderizar(
                        df_res, col_texto, col_num, modelo=item.modelo_grafico
                    )
                    img_chart = Image(buf_grafico, width=7.2 * inch, height=2.2 * inch)
                    sub_elementos.append(img_chart)
                    sub_elementos.append(Spacer(1, 5))

                if item.conclusao_negocio and item.conclusao_negocio.strip():
                    sub_elementos.append(self._construir_box_conclusao(item.conclusao_negocio.strip()))

                if idx < total_blocos - 1:
                    sub_elementos.append(Spacer(1, 14))
                    sub_elementos.append(
                        HRFlowable(
                            width="100%", thickness=0.5, color=colors.HexColor("#CBD5E1"), spaceBefore=0, spaceAfter=10
                        )
                    )

                elementos.append(KeepTogether(sub_elementos))

        doc.build(elementos, canvasmaker=NumberedCanvasExecutivo)
        return caminho_final

def main() -> None:
    # -------------------------------------------------------------------------
    # COLOQUE O NOME DO CANDIDATO, MUNICÍPIO E ANO AQUI:
    # -------------------------------------------------------------------------
    CANDIDATO_ENTRADA = "Ulysses do Psol"  # <-- COLOQUE O NOME AQUI (Ex: "Eduardo Paes")
    MUNICIPIO_ENTRADA = None   # <-- Opcional (ajuda na busca exata)
    ANO_ELEICAO = None                   # <-- Opcional (padrão é o ano mais recente)

    gerador = ExecutivePDFGenerator()
    
    print(f"Gerando Dossiê Executivo C-Level para: '{CANDIDATO_ENTRADA}'...")
    pdf_caminho = gerador.gerar_pdf(
        nome_candidato=CANDIDATO_ENTRADA,
        ano=ANO_ELEICAO,
        municipio=MUNICIPIO_ENTRADA,
    )

    print(f"\n[SUCESSO COMPROVADO] Dossiê C-Level com Benchmarks de CPV gerado em: '{pdf_caminho.resolve()}'")

if __name__ == "__main__":
    main()