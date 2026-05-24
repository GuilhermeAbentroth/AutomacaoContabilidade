import sqlite3
import os
import re
import time
import threading
import requests
import customtkinter as ctk
from tkinter import messagebox


class MonitorNotas:
    """
    Monitora notas emitidas via DPS e baixa os PDFs automaticamente
    quando a prefeitura conclui o processamento assíncrono.

    Fluxo:
      1. Após emissão bem-sucedida, registrar_pendente() salva o protocolo.
      2. A thread de polling acorda a cada 15s e consulta ConsultarStatusDps.
      3. Quando status = "Processado com sucesso", baixa o PDF e encerra
         o acompanhamento daquela nota.
      4. Quando não há mais nenhuma nota PENDENTE, a thread para sozinha.
    """

    INTERVALO_POLLING = 15          # segundos entre cada ciclo
    MAX_TENTATIVAS    = 240         # 240 × 15s = 1 hora antes de expirar
    URL_WS            = "https://nota-eletronica.betha.cloud/dps/ws"
    IBGE_PRESTADOR    = "4208906"   # Jaraguá do Sul — cidade do emitente

    # ------------------------------------------------------------------
    def __init__(self, db_path: str, pasta_pdfs: str, log_fn=None):
        self.db_path    = db_path
        self.pasta_pdfs = pasta_pdfs
        self.log_fn     = log_fn or (lambda msg, tipo="info": print(f"[MONITOR] {msg}"))
        self._thread    = None
        self._parar     = False
        self._criar_tabela()

        # Retoma notas pendentes que ficaram abertas em sessão anterior
        if self.tem_pendentes():
            self.log_fn("Monitor: notas pendentes encontradas. Retomando acompanhamento...", "info")
            self._iniciar_thread()

    # ------------------------------------------------------------------
    # Banco de dados
    # ------------------------------------------------------------------
    def _criar_tabela(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notas_pendentes (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    protocolo       TEXT    NOT NULL,
                    cnpj_prestador  TEXT    NOT NULL,
                    nome_tomador    TEXT    NOT NULL,
                    status          TEXT    DEFAULT 'PENDENTE',
                    tentativas      INTEGER DEFAULT 0,
                    dt_emissao      TEXT,
                    nome_prestador  TEXT,
                    dt_conclusao    TEXT,
                    numero_nota     TEXT,
                    link_pdf        TEXT,
                    caminho_pdf     TEXT
                )
            """)
            try:
                conn.execute("ALTER TABLE notas_pendentes ADD COLUMN nome_prestador TEXT")
                conn.commit()
            except Exception:
                pass

    def registrar_pendente(self, protocolo, cnpj_prestador, nome_tomador, nome_prestador):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                         INSERT INTO notas_pendentes
                         (protocolo, cnpj_prestador, nome_tomador, nome_prestador, status, tentativas, dt_emissao)
                         VALUES (?, ?, ?, ?, 'PENDENTE', 0, datetime('now', 'localtime'))
                         """, (protocolo, cnpj_prestador, nome_tomador, nome_prestador))
            conn.commit()
        self.log_fn(
            f"Monitor: acompanhamento iniciado → Protocolo {protocolo} | Tomador: {nome_tomador}",
            "info"
        )
        self._iniciar_thread()

    def listar_notas(self, filtro_status: str = None):
        with sqlite3.connect(self.db_path) as conn:
            if filtro_status:
                rows = conn.execute("""
                    SELECT id, protocolo, nome_prestador, nome_tomador, status,
                           dt_emissao, dt_conclusao, numero_nota, caminho_pdf
                    FROM notas_pendentes
                    WHERE status = ?
                    ORDER BY dt_emissao DESC
                """, (filtro_status,)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, protocolo, nome_prestador, nome_tomador, status,
                           dt_emissao, dt_conclusao, numero_nota, caminho_pdf
                    FROM notas_pendentes
                    ORDER BY dt_emissao DESC
                """).fetchall()
        return rows

    def tem_pendentes(self) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM notas_pendentes WHERE status = 'PENDENTE'"
            ).fetchone()[0]
        return count > 0

    def retentar_expiradas(self):
        """Recoloca notas EXPIRADO / ERRO_PREFEITURA como PENDENTE."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE notas_pendentes
                SET status = 'PENDENTE', tentativas = 0, dt_conclusao = NULL
                WHERE status IN ('EXPIRADO', 'ERRO_PREFEITURA')
            """)
            conn.commit()
        self._iniciar_thread()

    def _buscar_pendentes(self):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("""
                SELECT id, protocolo, cnpj_prestador, nome_tomador, nome_prestador, tentativas
                FROM notas_pendentes WHERE status = 'PENDENTE'
            """).fetchall()

    def _atualizar_nota(self, id_nota, status, numero_nota=None,
                        link_pdf=None, caminho_pdf=None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE notas_pendentes
                SET status = ?, numero_nota = ?, link_pdf = ?, caminho_pdf = ?,
                    dt_conclusao = datetime('now', 'localtime')
                WHERE id = ?
            """, (status, numero_nota, link_pdf, caminho_pdf, id_nota))
            conn.commit()

    def _incrementar_tentativas(self, id_nota, tentativas):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE notas_pendentes SET tentativas = ? WHERE id = ?",
                (tentativas, id_nota)
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Thread de polling
    # ------------------------------------------------------------------
    def _iniciar_thread(self):
        if self._thread and self._thread.is_alive():
            return  # já está rodando, não abre outra
        self._parar  = False
        self._thread = threading.Thread(target=self._loop_polling, daemon=True)
        self._thread.start()
        self.log_fn("Monitor: thread de acompanhamento ativa (intervalo: 15s).", "info")

    def _loop_polling(self):
        while not self._parar:
            pendentes = self._buscar_pendentes()

            if not pendentes:
                self.log_fn(
                    "Monitor: todas as notas foram processadas. Thread encerrada ✅",
                    "sucesso"
                )
                break

            for nota in pendentes:
                id_nota, protocolo, cnpj_prest, nome_tomador, nome_prestador, tentativas = nota
                resultado, numero_nota, link_pdf = self._consultar_status(protocolo, cnpj_prest)

                if resultado == "SUCESSO":
                    caminho = self._baixar_pdf(link_pdf, nome_tomador, numero_nota, nome_prestador)
                    self._atualizar_nota(id_nota, "CONCLUIDO", numero_nota, link_pdf, caminho)
                    self.log_fn(
                        f"✅ NFS-e nº {numero_nota} de '{nome_tomador}' "
                        f"{'salva em: ' + caminho if caminho else 'baixada (sem link PDF).'}",
                        "sucesso"
                    )

                elif resultado == "ERRO":
                    self._atualizar_nota(id_nota, "ERRO_PREFEITURA")
                    self.log_fn(
                        f"❌ Nota de '{nome_tomador}' rejeitada pela prefeitura. "
                        f"Verifique no portal.",
                        "erro"
                    )

                else:  # AGUARDANDO
                    novas_tent = tentativas + 1
                    if novas_tent >= self.MAX_TENTATIVAS:
                        self._atualizar_nota(id_nota, "EXPIRADO")
                        self.log_fn(
                            f"⚠️ Timeout para nota de '{nome_tomador}' "
                            f"(1h sem resposta). Verifique no portal.",
                            "erro"
                        )
                    else:
                        self._incrementar_tentativas(id_nota, novas_tent)

            time.sleep(self.INTERVALO_POLLING)

    # ------------------------------------------------------------------
    # SOAP — ConsultarStatusDps
    # ------------------------------------------------------------------
    def _consultar_status(self, protocolo: str, cnpj_prestador: str):
        """
        Retorna tupla: (resultado, numero_nota, link_pdf)
        resultado ∈ {"SUCESSO", "ERRO", "AGUARDANDO"}
        """
        envelope = (
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:e="http://www.betha.com.br/e-nota-dps">'
            '<soapenv:Header/>'
            '<soapenv:Body>'
            '<e:ConsultarStatusDpsEnvio>'
            f'<e:tpAmb>1</e:tpAmb>'
            f'<e:codigoIbge>{self.IBGE_PRESTADOR}</e:codigoIbge>'
            f'<e:cpfCnpjPrestador>{cnpj_prestador}</e:cpfCnpjPrestador>'
            f'<e:protocolo>{protocolo}</e:protocolo>'
            '<e:tipoIntegracao>EMISSAO</e:tipoIntegracao>'
            '</e:ConsultarStatusDpsEnvio>'
            '</soapenv:Body>'
            '</soapenv:Envelope>'
        )
        try:
            resp = requests.post(
                self.URL_WS,
                data=envelope.encode('utf-8'),
                headers={'Content-Type': 'text/xml;charset=UTF-8'},
                timeout=30
            )
            if resp.status_code != 200:
                return "AGUARDANDO", None, None

            texto = resp.text

            status_m = re.search(r'statusProcessamento>(.*?)</', texto,
                                  re.IGNORECASE | re.DOTALL)
            if not status_m:
                return "AGUARDANDO", None, None

            status_txt = status_m.group(1).strip().lower()

            if "sucesso" in status_txt:
                num_m  = re.search(r'numeroNotaFiscal>(.*?)</', texto, re.IGNORECASE)
                link_m = re.search(r'linkPdf>(.*?)</',          texto, re.IGNORECASE)
                numero = num_m.group(1).strip()  if num_m  else "SN"
                link   = link_m.group(1).strip() if link_m else None
                return "SUCESSO", numero, link

            if "erro" in status_txt:
                return "ERRO", None, None

            return "AGUARDANDO", None, None

        except Exception:
            return "AGUARDANDO", None, None

    # ------------------------------------------------------------------
    # Download do PDF
    # ------------------------------------------------------------------
    def _baixar_pdf(self, link_pdf, nome_tomador, numero_nota, nome_prestador):
        if not link_pdf:
            return None
        try:
            # Sanitiza nome da pasta (remove caracteres inválidos no Windows)
            nome_pasta = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', nome_prestador).strip()[:60]
            pasta_dest = os.path.join(self.pasta_pdfs, nome_pasta)
            os.makedirs(pasta_dest, exist_ok=True)

            nome_arq = f"NFSE_{numero_nota}.pdf"
            caminho  = os.path.join(pasta_dest, nome_arq)

            resp = requests.get(link_pdf, timeout=30)
            if resp.status_code == 200:
                with open(caminho, 'wb') as f:
                    f.write(resp.content)
                return caminho
        except Exception as e:
            self.log_fn(f"Monitor: erro ao baixar PDF — {e}", "erro")
        return None


# ======================================================================
# Tela de acompanhamento (UI)
# ======================================================================
class TelaMonitor:
    """
    Tela que exibe todas as notas registradas pelo MonitorNotas,
    com filtro por status e opção de abrir o PDF diretamente.
    """

    CORES_STATUS = {
        "PENDENTE":       "#e67e22",
        "CONCLUIDO":      "#27ae60",
        "EXPIRADO":       "#c0392b",
        "ERRO_PREFEITURA": "#c0392b",
    }

    def __init__(self, parent, monitor: MonitorNotas):
        self.parent  = parent
        self.monitor = monitor

    def abrir(self):
        self.parent.limpar_tela()

        # --- Cabeçalho ---
        f_header = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_header.pack(pady=5, fill="x")
        ctk.CTkLabel(
            f_header, text="📋 Acompanhamento de NFS-e",
            font=("Arial", 20, "bold"), text_color="#1f538d"
        ).pack(pady=5)

        # --- Filtros ---
        f_filtros = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_filtros.pack(fill="x", padx=40, pady=3)

        ctk.CTkLabel(f_filtros, text="Filtrar:", font=("Arial", 12, "bold")).pack(side="left")
        self.combo_filtro = ctk.CTkComboBox(
            f_filtros,
            values=["TODOS", "PENDENTE", "CONCLUIDO", "EXPIRADO", "ERRO_PREFEITURA"],
            width=160, state="readonly", command=self._atualizar_lista
        )
        self.combo_filtro.set("TODOS")
        self.combo_filtro.pack(side="left", padx=10)

        ctk.CTkButton(
            f_filtros, text="🔄 Atualizar", width=110,
            fg_color="#1f538d", hover_color="#14375e",
            command=self._atualizar_lista
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            f_filtros, text="↩ Retentar Expiradas", width=160,
            fg_color="#e67e22", hover_color="#d35400",
            command=self._retentar
        ).pack(side="left", padx=5)

        # --- Área de cards ---
        self.frame_lista = ctk.CTkScrollableFrame(self.parent.container)
        self.frame_lista.pack(fill="both", expand=True, padx=40, pady=5)

        # --- Rodapé ---
        f_btns = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_btns.pack(pady=10)
        ctk.CTkButton(
            f_btns, text="Voltar ao Menu", width=140, height=40, fg_color="gray",
            command=self.parent.mostrar_menu_inicial
        ).pack()

        self._atualizar_lista()

    def _atualizar_lista(self, *_):
        # Limpa cards anteriores
        for widget in self.frame_lista.winfo_children():
            widget.destroy()

        filtro = self.combo_filtro.get()
        notas  = self.monitor.listar_notas(None if filtro == "TODOS" else filtro)

        if not notas:
            ctk.CTkLabel(
                self.frame_lista,
                text="Nenhuma nota encontrada para o filtro selecionado.",
                font=("Arial", 13), text_color="gray"
            ).pack(pady=30)
            return

        for nota in notas:
            id_nota, protocolo, nome_prestador, nome_tomador, status, \
            dt_emissao, dt_conclusao, numero_nota, caminho_pdf = nota

            cor = self.CORES_STATUS.get(status, "#555555")

            card = ctk.CTkFrame(self.frame_lista, border_width=1, border_color=cor)
            card.pack(fill="x", pady=4, padx=5)

            # Linha 1: status + tomador
            f1 = ctk.CTkFrame(card, fg_color="transparent")
            f1.pack(fill="x", padx=10, pady=(6, 2))

            ctk.CTkLabel(
                f1, text=f"● {status}", font=("Arial", 11, "bold"),
                text_color=cor, width=160, anchor="w"
            ).pack(side="left")

            ctk.CTkLabel(
                f1, text=f"{nome_prestador or '—'}  →  {nome_tomador}",
                font=("Arial", 12, "bold"), anchor="w"
            ).pack(side="left", padx=10)

            if numero_nota:
                ctk.CTkLabel(
                    f1, text=f"NFSE nº {numero_nota}",
                    font=("Arial", 11), text_color="#27ae60"
                ).pack(side="right", padx=10)

            # Linha 2: protocolo + datas
            f2 = ctk.CTkFrame(card, fg_color="transparent")
            f2.pack(fill="x", padx=10, pady=(0, 2))

            ctk.CTkLabel(
                f2, text=f"Protocolo: {protocolo[:40]}...",
                font=("Arial", 9), text_color="gray", anchor="w"
            ).pack(side="left")

            data_txt = f"Emitida: {dt_emissao or '—'}"
            if dt_conclusao:
                data_txt += f"  |  Concluída: {dt_conclusao}"
            ctk.CTkLabel(
                f2, text=data_txt,
                font=("Arial", 9), text_color="gray"
            ).pack(side="right", padx=10)

            # Botão abrir PDF
            if caminho_pdf and os.path.exists(caminho_pdf):
                ctk.CTkButton(
                    card, text="📄 Abrir PDF", width=110, height=26,
                    fg_color="#27ae60", hover_color="#218c4e",
                    command=lambda p=caminho_pdf: self._abrir_pdf(p)
                ).pack(anchor="e", padx=10, pady=(0, 6))
            elif status == "PENDENTE":
                ctk.CTkLabel(
                    card, text="⏳ Aguardando processamento...",
                    font=("Arial", 10), text_color="#e67e22"
                ).pack(anchor="e", padx=10, pady=(0, 6))

    def _retentar(self):
        self.monitor.retentar_expiradas()
        self._atualizar_lista()
        self.parent.log_msg("Monitor: notas expiradas recolocadas na fila.", "info")

    def _abrir_pdf(self, caminho: str):
        try:
            os.startfile(caminho)
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível abrir o PDF:\n{e}")