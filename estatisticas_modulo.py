import sqlite3
import tkinter as tk
import customtkinter as ctk


class EstatisticasModulo:
    """Contador de uso interno (extratos convertidos, notas baixadas/emitidas,
    unificações fiscais). Grava um registro por evento no mesmo banco SQLite
    já usado pelo módulo Betha (chave 'caminho_banco' das configurações)."""

    EVENTOS = {
        "extrato_convertido": "Extratos Convertidos",
        "nota_baixada": "Notas Baixadas",
        "nota_emitida": "Notas Emitidas",
        "fiscal_unificacao": "Unificações no Módulo Fiscal",
    }

    def __init__(self, parent):
        self.parent = parent
        self._criar_tabela()

    def _conectar(self):
        caminho = self.parent.configuracoes.get("caminho_banco")
        return sqlite3.connect(caminho, timeout=10)

    def _criar_tabela(self):
        try:
            with self._conectar() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS estatisticas_uso (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        evento TEXT NOT NULL,
                        data_hora TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                    )
                """)
        except Exception:
            pass

    def registrar_evento(self, evento: str):
        """Incrementa o contador de um evento. Nunca lança exceção:
        uma falha aqui não deve interromper o fluxo principal (conversão,
        emissão, etc.)."""
        try:
            with self._conectar() as conn:
                conn.execute("INSERT INTO estatisticas_uso (evento) VALUES (?)", (evento,))
        except Exception:
            pass

    def obter_contagens(self) -> dict:
        contagens = {chave: 0 for chave in self.EVENTOS}
        try:
            with self._conectar() as conn:
                cur = conn.execute("SELECT evento, COUNT(*) FROM estatisticas_uso GROUP BY evento")
                for evento, qtd in cur.fetchall():
                    if evento in contagens:
                        contagens[evento] = qtd
        except Exception:
            pass
        return contagens

    def abrir_tela_estatisticas(self):
        janela = ctk.CTkToplevel(self.parent.root)
        janela.title("Estatísticas de Uso")
        janela.geometry("480x360")
        janela.transient(self.parent.root)
        janela.grab_set()

        x = (janela.winfo_screenwidth() // 2) - 240
        y = (janela.winfo_screenheight() // 2) - 180
        janela.geometry(f"480x360+{x}+{y}")

        ctk.CTkLabel(janela, text="📊 Estatísticas de Uso", font=("Arial", 18, "bold")).pack(pady=(20, 10))

        f_tabela = ctk.CTkFrame(janela)
        f_tabela.pack(fill="both", expand=True, padx=20, pady=10)

        contagens = self.obter_contagens()
        for chave, titulo in self.EVENTOS.items():
            f_linha = ctk.CTkFrame(f_tabela, fg_color="transparent")
            f_linha.pack(fill="x", padx=15, pady=8)
            ctk.CTkLabel(f_linha, text=titulo, font=("Arial", 12), anchor="w").pack(side=tk.LEFT)
            ctk.CTkLabel(f_linha, text=str(contagens[chave]), font=("Arial", 12, "bold"),
                         text_color="#1f538d").pack(side=tk.RIGHT)

        ctk.CTkButton(janela, text="Fechar", command=janela.destroy).pack(pady=(0, 20))
