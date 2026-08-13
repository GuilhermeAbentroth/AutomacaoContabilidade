import sqlite3
import os
import re
import time
import threading
import requests
import customtkinter as ctk
from tkinter import messagebox
from lxml import etree
from signxml import XMLSigner
from certificado_utils import CertificadoA1


class MonitorNotas:
    """
    Monitora notas emitidas via DPS e baixa os PDFs e XMLs automaticamente
    quando a prefeitura conclui o processamento assíncrono.

    Fluxo:
      1. Após emissão bem-sucedida, registrar_pendente() salva o protocolo.
      2. A thread de polling acorda a cada 15s e consulta ConsultarStatusDps.
      3. Quando status = "Processado com sucesso", baixa o PDF e o XML.
      4. Quando não há mais nenhuma nota PENDENTE, a thread para sozinha.
    """

    INTERVALO_POLLING = 15  # segundos entre cada ciclo
    MAX_TENTATIVAS = 240  # 240 × 15s = 1 hora antes de expirar
    URL_WS = "https://nota-eletronica.betha.cloud/dps/ws"
    IBGE_PRESTADOR = "4208906"  # Jaraguá do Sul — cidade do emitente

    # ------------------------------------------------------------------
    def __init__(self, db_path: str, pasta_pdfs: str, log_fn=None):
        self.db_path = db_path
        self.pasta_pdfs = pasta_pdfs
        self.log_fn = log_fn or (lambda msg, tipo="info": print(f"[MONITOR] {msg}"))
        self._thread = None
        self._parar = False
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
                         CREATE TABLE IF NOT EXISTS notas_pendentes
                         (
                             id
                             INTEGER
                             PRIMARY
                             KEY
                             AUTOINCREMENT,
                             protocolo
                             TEXT
                             NOT
                             NULL,
                             cnpj_prestador
                             TEXT
                             NOT
                             NULL,
                             nome_tomador
                             TEXT
                             NOT
                             NULL,
                             status
                             TEXT
                             DEFAULT
                             'PENDENTE',
                             tentativas
                             INTEGER
                             DEFAULT
                             0,
                             dt_emissao
                             TEXT,
                             nome_prestador
                             TEXT,
                             dt_conclusao
                             TEXT,
                             numero_nota
                             TEXT,
                             link_pdf
                             TEXT,
                             caminho_pdf
                             TEXT
                         )
                         """)

            # Executando migrations para adicionar novas colunas
            migrations = [
                ("nome_prestador", "TEXT"),
                ("caminho_xml", "TEXT"),
                ("chave_acesso", "TEXT"),
                ("protocolo_cancelamento", "TEXT")
            ]

            for col, t in migrations:
                try:
                    conn.execute(f"ALTER TABLE notas_pendentes ADD COLUMN {col} {t}")
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

    def listar_notas(self, filtro_status=None, filtro_prestador=None, filtro_data=None):
        with sqlite3.connect(self.db_path) as conn:
            base = """
                   SELECT id, \
                          protocolo, \
                          nome_prestador, \
                          nome_tomador, \
                          status,
                          dt_emissao, \
                          dt_conclusao, \
                          numero_nota, \
                          caminho_pdf
                   FROM notas_pendentes \
                   WHERE 1 = 1 \
                   """
            params = []
            if filtro_status:
                base += " AND status = ?"
                params.append(filtro_status)
            if filtro_prestador:
                base += " AND UPPER(nome_prestador) LIKE ?"
                params.append(f"%{filtro_prestador.upper()}%")
            if filtro_data:
                base += " AND dt_emissao LIKE ?"
                params.append(f"{filtro_data}%")
            base += " ORDER BY dt_emissao DESC"
            return conn.execute(base, params).fetchall()

    def tem_pendentes(self) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM notas_pendentes WHERE status IN ('PENDENTE', 'CANCELAMENTO_PENDENTE')"
            ).fetchone()[0]
        return count > 0

    def retentar_expiradas(self):
        """Recoloca notas EXPIRADO / ERRO_PREFEITURA como PENDENTE."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                         UPDATE notas_pendentes
                         SET status       = 'PENDENTE',
                             tentativas   = 0,
                             dt_conclusao = NULL
                         WHERE status IN ('EXPIRADO', 'ERRO_PREFEITURA')
                         """)
            conn.commit()
        self._iniciar_thread()

    def _buscar_cancelamentos_pendentes(self):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("""
                                SELECT id, protocolo_cancelamento, cnpj_prestador, nome_tomador
                                FROM notas_pendentes
                                WHERE status = 'CANCELAMENTO_PENDENTE'
                                  AND protocolo_cancelamento IS NOT NULL
                                """).fetchall()

    def _consultar_status_cancelamento(self, protocolo_cancel: str, cnpj_prestador: str) -> str:
        envelope = (
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:e="http://www.betha.com.br/e-nota-dps">'
            '<soapenv:Header/>'
            '<soapenv:Body>'
            '<e:ConsultarStatusDpsEnvio>'
            f'<e:tpAmb>1</e:tpAmb>'
            f'<e:codigoIbge>{self.IBGE_PRESTADOR}</e:codigoIbge>'
            f'<e:cpfCnpjPrestador>{cnpj_prestador}</e:cpfCnpjPrestador>'
            f'<e:protocolo>{protocolo_cancel}</e:protocolo>'
            '<e:tipoIntegracao>CANCELAMENTO</e:tipoIntegracao>'
            '</e:ConsultarStatusDpsEnvio>'
            '</soapenv:Body>'
            '</soapenv:Envelope>'
        )
        try:
            resp = requests.post(self.URL_WS, data=envelope.encode('utf-8'),
                                 headers={'Content-Type': 'text/xml;charset=UTF-8'}, timeout=30)
            if resp.status_code != 200:
                return "AGUARDANDO"
            status_m = re.search(r'statusProcessamento>(.*?)</', resp.text,
                                 re.IGNORECASE | re.DOTALL)
            if not status_m:
                return "AGUARDANDO"
            status_txt = status_m.group(1).strip().lower()
            if "sucesso" in status_txt:
                return "SUCESSO"
            if "erro" in status_txt:
                return "ERRO"
            return "AGUARDANDO"
        except Exception:
            return "AGUARDANDO"

    def _buscar_pendentes(self):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("""
                                SELECT id, protocolo, cnpj_prestador, nome_tomador, nome_prestador, tentativas
                                FROM notas_pendentes
                                WHERE status = 'PENDENTE'
                                """).fetchall()

    def _atualizar_nota(self, id_nota, status, numero_nota=None,
                        link_pdf=None, caminho_pdf=None,
                        caminho_xml=None, chave_acesso=None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                         UPDATE notas_pendentes
                         SET status       = ?,
                             numero_nota  = ?,
                             link_pdf     = ?,
                             caminho_pdf  = ?,
                             caminho_xml  = ?,
                             chave_acesso = ?,
                             dt_conclusao = datetime('now', 'localtime')
                         WHERE id = ?
                         """, (status, numero_nota, link_pdf, caminho_pdf,
                               caminho_xml, chave_acesso, id_nota))
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
        self._parar = False
        self._thread = threading.Thread(target=self._loop_polling, daemon=True)
        self._thread.start()
        self.log_fn("Monitor: thread de acompanhamento ativa (intervalo: 15s).", "info")

    def _loop_polling(self):
        while not self._parar:
            pendentes = self._buscar_pendentes()
            cancelamentos = self._buscar_cancelamentos_pendentes()

            if not pendentes and not cancelamentos:
                self.log_fn(
                    "Monitor: todas as notas foram processadas. Thread encerrada ✅",
                    "sucesso"
                )
                break

            # --- Processa emissões pendentes ---
            for nota in pendentes:
                id_nota, protocolo, cnpj_prest, nome_tomador, nome_prestador, tentativas = nota
                resultado, numero_nota, link_pdf, chave_acesso = self._consultar_status(
                    protocolo, cnpj_prest)

                if resultado == "SUCESSO":
                    caminho_pdf = self._baixar_pdf(link_pdf, nome_tomador,
                                                   numero_nota, nome_prestador)
                    caminho_xml = self._finalizar_xml(protocolo, numero_nota, nome_prestador, link_pdf)
                    self._atualizar_nota(id_nota, "CONCLUIDO", numero_nota,
                                         link_pdf, caminho_pdf, caminho_xml, chave_acesso)
                    self.log_fn(
                        f"✅ NFS-e nº {numero_nota} de '{nome_tomador}' "
                        f"{'salva em: ' + caminho_pdf if caminho_pdf else 'processada.'}",
                        "sucesso"
                    )
                elif resultado == "ERRO":
                    self._atualizar_nota(id_nota, "ERRO_PREFEITURA")
                    self.log_fn(
                        f"❌ Nota de '{nome_tomador}' rejeitada pela prefeitura.", "erro")
                else:
                    novas_tent = tentativas + 1
                    if novas_tent >= self.MAX_TENTATIVAS:
                        self._atualizar_nota(id_nota, "EXPIRADO")
                        self.log_fn(
                            f"⚠️ Timeout para nota de '{nome_tomador}' "
                            f"(1h sem resposta). Verifique no portal.", "erro")
                    else:
                        self._incrementar_tentativas(id_nota, novas_tent)

            # --- Processa cancelamentos pendentes ---
            for canc in cancelamentos:
                id_nota, protocolo_cancel, cnpj_prest, nome_tomador = canc
                resultado = self._consultar_status_cancelamento(protocolo_cancel, cnpj_prest)

                if resultado == "SUCESSO":
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute("""
                                     UPDATE notas_pendentes
                                     SET status       = 'CANCELADO',
                                         dt_conclusao = datetime('now', 'localtime')
                                     WHERE id = ?
                                     """, (id_nota,))
                    self.log_fn(
                        f"✅ Cancelamento da nota de '{nome_tomador}' confirmado.", "sucesso")
                elif resultado == "ERRO":
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute("""
                                     UPDATE notas_pendentes
                                     SET status = 'ERRO_PREFEITURA'
                                     WHERE id = ?
                                     """, (id_nota,))
                    self.log_fn(
                        f"❌ Erro no cancelamento da nota de '{nome_tomador}'.", "erro")

            time.sleep(self.INTERVALO_POLLING)

    def salvar_xml_emissao(self, xml_content: str, protocolo: str, nome_prestador: str):
        """Salva o XML assinado no momento da emissão com nome temporário (protocolo)."""
        try:
            nome_pasta = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', nome_prestador).strip()[:60]
            pasta_dest = os.path.join(self.pasta_pdfs, nome_pasta)
            os.makedirs(pasta_dest, exist_ok=True)

            protocolo_safe = re.sub(r'[^a-zA-Z0-9\-]', '', protocolo)[:30]
            caminho = os.path.join(pasta_dest, f"temp_{protocolo_safe}.xml")
            with open(caminho, 'w', encoding='utf-8') as f:
                f.write(xml_content)
        except Exception as e:
            self.log_fn(f"Monitor: erro ao salvar XML temporário — {e}", "erro")

    # ------------------------------------------------------------------
    # SOAP — ConsultarStatusDps
    # ------------------------------------------------------------------
    def _consultar_status(self, protocolo: str, cnpj_prestador: str):
        """
        Retorna tupla: (resultado, numero_nota, link_pdf, chave_acesso)
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
                return "AGUARDANDO", None, None, None

            texto = resp.text

            status_m = re.search(r'statusProcessamento>(.*?)</', texto,
                                 re.IGNORECASE | re.DOTALL)
            if not status_m:
                return "AGUARDANDO", None, None, None

            status_txt = status_m.group(1).strip().lower()

            if "sucesso" in status_txt:
                num_m = re.search(r'numeroNotaFiscal>(.*?)</', texto, re.IGNORECASE)
                link_m = re.search(r'linkPdf>(.*?)</', texto, re.IGNORECASE)
                chave_m = re.search(r'chaveAcesso>(.*?)</', texto, re.IGNORECASE)
                numero = num_m.group(1).strip() if num_m else "SN"
                link = link_m.group(1).strip() if link_m else None
                chave = chave_m.group(1).strip() if chave_m else None
                return "SUCESSO", numero, link, chave

            if "erro" in status_txt:
                return "ERRO", None, None, None

            return "AGUARDANDO", None, None, None

        except Exception:
            return "AGUARDANDO", None, None, None

    def verificar_cancelamentos_agora(self):
        """Força uma verificação imediata dos cancelamentos pendentes."""
        threading.Thread(target=self._processar_cancelamentos_agora, daemon=True).start()

    def _processar_cancelamentos_agora(self):
        cancelamentos = self._buscar_cancelamentos_pendentes()
        if not cancelamentos:
            return
        for canc in cancelamentos:
            id_nota, protocolo_cancel, cnpj_prest, nome_tomador = canc
            resultado = self._consultar_status_cancelamento(protocolo_cancel, cnpj_prest)
            if resultado == "SUCESSO":
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("""
                                 UPDATE notas_pendentes
                                 SET status       = 'CANCELADO',
                                     dt_conclusao = datetime('now', 'localtime')
                                 WHERE id = ?
                                 """, (id_nota,))
                self.log_fn(
                    f"✅ Cancelamento de '{nome_tomador}' confirmado.", "sucesso")
            elif resultado == "ERRO":
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("""
                                 UPDATE notas_pendentes
                                 SET status = 'ERRO_PREFEITURA'
                                 WHERE id = ?
                                 """, (id_nota,))
                self.log_fn(
                    f"❌ Erro no cancelamento de '{nome_tomador}'.", "erro")


    # ------------------------------------------------------------------
    # Cancelamento
    # ------------------------------------------------------------------
    def cancelar_nota(self, id_nota: int, chave_acesso: str,
                      cnpj_prestador: str, motivo_texto: str):
        """
        Envia o evento de cancelamento assinado digitalmente.
        Busca o certificado do prestador direto no banco de dados.
        """
        import time as _time
        # Busca certificado do prestador no banco
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute("""
                                   SELECT p.caminho_pfx, p.senha_pfx
                                   FROM prestadores p
                                   WHERE p.cnpj = ?
                                   """, (cnpj_prestador,)).fetchone()
            if not row:
                return False, "Certificado do prestador não encontrado no banco."
            caminho_pfx, senha_pfx = row
            cert_manager = CertificadoA1(caminho_pfx, senha_pfx)
            if not cert_manager.carregar_chaves(self.log_fn):
                return False, "Falha ao carregar o certificado digital."
        except Exception as e:
            return False, f"Erro ao buscar certificado: {e}"

        # Monta os IDs do evento
        ts = str(int(_time.time() * 1000))
        id_evento = f"EVT{chave_acesso[:40]}{ts[:15]}"
        id_ped_reg = f"PRE{chave_acesso[:40]}{ts[:12]}"
        dh_evento = _time.strftime('%Y-%m-%dT%H:%M:%S-03:00')

        # XML do evento de cancelamento (será assinado)
        xml_evento = f"""<evento xmlns="http://www.betha.com.br/e-nota-dps" versao="1.0">
            <infEvento id="{id_evento}">
                <verAplic>Abentroth_v8.0</verAplic>
                <ambGer>1</ambGer>
                <nSeqEvento>1</nSeqEvento>
                <dhProc>{dh_evento}</dhProc>
                <pedRegEvento versao="1.0">
                    <infPedReg id="{id_ped_reg}">
                        <chNFSe>{chave_acesso}</chNFSe>
                        <CNPJAutor>{cnpj_prestador}</CNPJAutor>
                        <dhEvento>{dh_evento}</dhEvento>
                        <tpAmb>1</tpAmb>
                        <verAplic>Abentroth_v8.0</verAplic>
                        <e101101>
                            <xDesc>Cancelamento de NFS-e</xDesc>
                            <cMotivo>1</cMotivo>
                            <xMotivo>{motivo_texto[:255]}</xMotivo>
                        </e101101>
                    </infPedReg>
                </pedRegEvento>
            </infEvento>
        </evento>"""

        try:
            # Assina o XML do evento
            root = etree.fromstring(xml_evento.encode('utf-8'))
            signed_root = XMLSigner().sign(
                root,
                key=cert_manager.obter_chave_privada_pem(),
                cert=cert_manager.obter_certificado_pem()
            )
            xml_assinado = etree.tostring(signed_root, encoding='utf-8',
                                          xml_declaration=False).decode('utf-8') \
                .replace('<?xml version="1.0" encoding="UTF-8"?>', '') \
                .replace('<?xml version="1.0" ?>', '').strip()

            # Monta o envelope SOAP
            envelope = (
                '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
                'xmlns="http://www.betha.com.br/e-nota-dps">'
                '<soapenv:Header/>'
                '<soapenv:Body>'
                f'<RecepcionarEventoCancelamentoEnvio>{xml_assinado}'
                '</RecepcionarEventoCancelamentoEnvio>'
                '</soapenv:Body>'
                '</soapenv:Envelope>'
            )

            resp = requests.post(
                self.URL_WS,
                data=envelope.encode('utf-8'),
                headers={'Content-Type': 'text/xml;charset=UTF-8'},
                timeout=60
            )

            if resp.status_code == 200:
                prot_m = re.search(r'protocolo>(.*?)</', resp.text, re.IGNORECASE)
                if prot_m:
                    protocolo_cancel = prot_m.group(1).strip()
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute("""
                                     UPDATE notas_pendentes
                                     SET status                 = 'CANCELAMENTO_PENDENTE',
                                         protocolo_cancelamento = ?
                                     WHERE id = ?
                                     """, (protocolo_cancel, id_nota))
                    self.log_fn(
                        f"Cancelamento enviado. Protocolo: {protocolo_cancel}", "sucesso")
                    return True, protocolo_cancel
                else:
                    msg_m = re.search(r'mensagem>(.*?)</', resp.text, re.IGNORECASE)
                    erro = msg_m.group(1) if msg_m else "Erro desconhecido"
                    self.log_fn(f"Cancelamento rejeitado: {erro}", "erro")
                    return False, erro
            else:
                return False, f"Erro HTTP {resp.status_code}"
        except Exception as e:
            self.log_fn(f"Erro ao assinar/enviar cancelamento: {e}", "erro")
            return False, str(e)

    # ------------------------------------------------------------------
    # Download do PDF e XML
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
            caminho = os.path.join(pasta_dest, nome_arq)

            resp = requests.get(link_pdf, timeout=30)
            if resp.status_code == 200:
                with open(caminho, 'wb') as f:
                    f.write(resp.content)
                return caminho
        except Exception as e:
            self.log_fn(f"Monitor: erro ao baixar PDF — {e}", "erro")
        return None

    def _finalizar_xml(self, protocolo: str, numero_nota: str,
                       nome_prestador: str, link_pdf: str = None):
        """
        Baixa o XML oficial da NFS-e da Betha (troca /pdf/ por /xml/ no link)
        e salva com o mesmo nome do PDF.
        Fallback: renomeia o XML temporário da emissão se o download falhar.
        """
        try:
            nome_pasta = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_',
                                nome_prestador).strip()[:60]
            pasta_dest = os.path.join(self.pasta_pdfs, nome_pasta)
            os.makedirs(pasta_dest, exist_ok=True)
            final_path = os.path.join(pasta_dest, f"NFSE_{numero_nota}.xml")

            # Tenta baixar o XML oficial da Betha
            if link_pdf and "/pdf/" in link_pdf:
                link_xml = link_pdf.replace("/pdf/", "/xml/")
                resp = requests.get(link_xml, timeout=30)
                if resp.status_code == 200:
                    with open(final_path, 'wb') as f:
                        f.write(resp.content)
                    self.log_fn(f"XML oficial salvo: NFSE_{numero_nota}.xml", "info")
                    return final_path
                else:
                    self.log_fn(
                        f"XML oficial não disponível (HTTP {resp.status_code}). "
                        f"Usando XML da emissão.", "info")

            # Fallback: renomeia o XML temporário da emissão
            protocolo_safe = re.sub(r'[^a-zA-Z0-9\-]', '', protocolo)[:30]
            temp_path = os.path.join(pasta_dest, f"temp_{protocolo_safe}.xml")
            if os.path.exists(temp_path):
                os.rename(temp_path, final_path)
                self.log_fn(f"XML da emissão salvo: NFSE_{numero_nota}.xml", "info")
                return final_path

            self.log_fn("XML não disponível.", "erro")
            return None

        except Exception as e:
            self.log_fn(f"Monitor: erro ao baixar XML — {e}", "erro")
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
        "PENDENTE": "#e67e22",
        "CONCLUIDO": "#27ae60",
        "CANCELAMENTO_PENDENTE": "#e67e22",
        "CANCELADO": "#7f8c8d",
        "EXPIRADO": "#c0392b",
        "ERRO_PREFEITURA": "#c0392b",
    }

    def __init__(self, parent, monitor: MonitorNotas):
        self.parent = parent
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
            values=["TODOS", "PENDENTE", "CONCLUIDO", "CANCELAMENTO_PENDENTE",
                    "CANCELADO", "EXPIRADO", "ERRO_PREFEITURA"],
            width=160, state="readonly", command=self._atualizar_lista
        )
        self.combo_filtro.set("TODOS")
        self.combo_filtro.pack(side="left", padx=10)



        ctk.CTkButton(
            f_filtros, text="🔄 Atualizar", width=110,
            fg_color="#1f538d", hover_color="#14375e",
            command=self._atualizar_com_verificacao
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            f_filtros, text="↩ Retentar Expiradas", width=160,
            fg_color="#e67e22", hover_color="#d35400",
            command=self._retentar
        ).pack(side="left", padx=5)

        ctk.CTkLabel(f_filtros, text="Prestador:", font=("Arial", 11)).pack(side="left", padx=(15, 3))
        self.ent_filtro_prestador = ctk.CTkEntry(f_filtros, placeholder_text="Nome do prestador...",
                                                 width=180, height=28)
        self.ent_filtro_prestador.pack(side="left", padx=3)

        # Filtro por Data
        ctk.CTkLabel(f_filtros, text="Data:", font=("Arial", 11)).pack(side="left", padx=(10, 3))
        self.ent_filtro_data = ctk.CTkEntry(f_filtros, placeholder_text="DD/MM/AAAA",
                                            width=110, height=28)
        self.ent_filtro_data.pack(side="left", padx=3)
        ctk.CTkButton(f_filtros, text="🔍", width=40, height=28,
                      fg_color="#1f538d", hover_color="#14375e",
                      command=self._atualizar_lista).pack(side="left", padx=(0, 5))

        # Bind Enter nos campos de filtro
        self.ent_filtro_prestador.bind("<Return>", lambda e: self._atualizar_lista())
        self.ent_filtro_data.bind("<Return>", lambda e: self._atualizar_lista())

        # Botão limpar filtros
        ctk.CTkButton(f_filtros, text="✖ Limpar", width=80, height=28,
                      fg_color="#7f8c8d", hover_color="#636e72",
                      command=self._limpar_filtros).pack(side="left", padx=5)

        # --- Área de cards ---
        self.frame_lista = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        self.frame_lista.pack(fill="both", expand=True, padx=40, pady=5)

        # --- Rodapé ---
        f_btns = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_btns.pack(pady=10)
        ctk.CTkButton(
            f_btns, text="Voltar ao Menu", width=140, height=40, fg_color="gray",
            command=self.parent.mostrar_menu_inicial
        ).pack()

        self._atualizar_lista()

    def _limpar_filtros(self):
        self.ent_filtro_prestador.delete(0, "end")
        self.ent_filtro_data.delete(0, "end")
        self.combo_filtro.set("TODOS")
        self._atualizar_lista()

    def _atualizar_com_verificacao(self):
        """Verifica cancelamentos pendentes e atualiza a lista após 2s."""
        self.monitor.verificar_cancelamentos_agora()
        # Aguarda 2s para a consulta retornar antes de redesenhar
        self.parent.root.after(2000, self._atualizar_lista)

    def _atualizar_lista(self, *_):
        for widget in self.frame_lista.winfo_children():
            widget.destroy()

        filtro_status = self.combo_filtro.get()
        filtro_prestador = self.ent_filtro_prestador.get().strip()
        filtro_data_raw = self.ent_filtro_data.get().strip()

        # Converte data DD/MM/AAAA → AAAA-MM-DD para busca no banco
        filtro_data = None
        if filtro_data_raw and len(filtro_data_raw) == 10:
            try:
                from datetime import datetime
                filtro_data = datetime.strptime(filtro_data_raw, "%d/%m/%Y").strftime("%Y-%m-%d")
            except Exception:
                pass

        notas = self.monitor.listar_notas(
            filtro_status=None if filtro_status == "TODOS" else filtro_status,
            filtro_prestador=filtro_prestador or None,
            filtro_data=filtro_data
        )

        if not notas:
            ctk.CTkLabel(
                self.frame_lista,
                text="Nenhuma nota encontrada para os filtros selecionados.",
                font=("Arial", 13), text_color="gray"
            ).pack(pady=30)
            return

        for nota in notas:
            id_nota, protocolo, nome_prestador, nome_tomador, status, \
                dt_emissao, dt_conclusao, numero_nota, caminho_pdf = nota

            cor = self.CORES_STATUS.get(status, "#555555")

            card = ctk.CTkFrame(self.frame_lista, border_width=1, border_color=cor)
            card.pack(fill="x", pady=2, padx=5)

            # Linha 1: status + prestador → tomador + número
            f1 = ctk.CTkFrame(card, fg_color="transparent")
            f1.pack(fill="x", padx=10, pady=(5, 2))

            ctk.CTkLabel(
                f1, text=f"● {status}", font=("Arial", 11, "bold"),
                text_color=cor, width=180, anchor="w"
            ).pack(side="left")

            ctk.CTkLabel(
                f1, text=f"{nome_prestador or '—'}  →  {nome_tomador}",
                font=("Arial", 12, "bold"), anchor="w"
            ).pack(side="left", padx=10)

            if numero_nota:
                ctk.CTkLabel(
                    f1, text=f"NF nº {numero_nota}",
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

            # Linha 3: botões — só para status que têm ação
            tem_botao = False
            f3 = ctk.CTkFrame(card, fg_color="transparent")

            if caminho_pdf and os.path.exists(caminho_pdf):
                ctk.CTkButton(
                    f3, text="📄 Abrir PDF", width=110, height=26,
                    fg_color="#27ae60", hover_color="#218c4e",
                    command=lambda p=caminho_pdf: self._abrir_arquivo(p)
                ).pack(side="left", padx=(0, 5))
                tem_botao = True

            if caminho_pdf:
                caminho_xml = caminho_pdf.replace(".pdf", ".xml")
                if os.path.exists(caminho_xml):
                    ctk.CTkButton(
                        f3, text="📋 Abrir XML", width=110, height=26,
                        fg_color="#1f538d", hover_color="#14375e",
                        command=lambda x=caminho_xml: self._abrir_arquivo(x)
                    ).pack(side="left", padx=5)
                    tem_botao = True

            if status == "CONCLUIDO":
                with sqlite3.connect(self.monitor.db_path) as conn:
                    row = conn.execute("""
                                       SELECT chave_acesso, cnpj_prestador
                                       FROM notas_pendentes
                                       WHERE id = ?
                                       """, (id_nota,)).fetchone()
                chave_acesso = row[0] if row and row[0] else ""
                cnpj_prest = row[1] if row and row[1] else ""
                if chave_acesso:
                    ctk.CTkButton(
                        f3, text="🗑️ Cancelar NF", width=130, height=26,
                        fg_color="#c0392b", hover_color="#962d22",
                        command=lambda i=id_nota, c=chave_acesso,
                                       cnpj=cnpj_prest: self._popup_cancelamento(i, c, cnpj)
                    ).pack(side="right", padx=5)
                    tem_botao = True

            elif status == "PENDENTE":
                ctk.CTkLabel(f3, text="⏳ Aguardando processamento...",
                             font=("Arial", 10), text_color="#e67e22").pack(side="right")
                tem_botao = True

            elif status == "CANCELAMENTO_PENDENTE":
                ctk.CTkLabel(f3, text="⏳ Cancelamento em processamento...",
                             font=("Arial", 10), text_color="#e67e22").pack(side="right")
                tem_botao = True

            # Só exibe f3 se tiver conteúdo — evita card grande desnecessário
            if tem_botao:
                f3.pack(fill="x", padx=10, pady=(0, 5))
            else:
                card.pack(fill="x", pady=2, padx=5)

    def _retentar(self):
        self.monitor.retentar_expiradas()
        self._atualizar_lista()
        self.parent.log_msg("Monitor: notas expiradas recolocadas na fila.", "info")

    def _abrir_arquivo(self, caminho: str):
        try:
            os.startfile(caminho)
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível abrir o arquivo:\n{e}")

    def _popup_cancelamento(self, id_nota, chave_acesso, cnpj_prestador):
        popup = ctk.CTkToplevel(self.parent.root)
        popup.title("Cancelar NFS-e")
        popup.geometry("440x300")
        popup.resizable(False, False)
        popup.transient(self.parent.root)
        popup.grab_set()

        x = (popup.winfo_screenwidth() // 2) - 220
        y = (popup.winfo_screenheight() // 2) - 150
        popup.geometry(f"440x300+{x}+{y}")

        ctk.CTkLabel(popup, text="🗑️ Cancelar NFS-e",
                     font=("Arial", 16, "bold"), text_color="#c0392b").pack(pady=15)

        ctk.CTkLabel(popup, text="Informe o motivo do cancelamento:",
                     font=("Arial", 12)).pack()

        txt_motivo = ctk.CTkTextbox(popup, height=90, width=390)
        txt_motivo.pack(pady=10, padx=25)

        lbl_status = ctk.CTkLabel(popup, text="", font=("Arial", 11),
                                  text_color="#c0392b", wraplength=380)
        lbl_status.pack(pady=3)

        def confirmar():
            motivo = txt_motivo.get("1.0", "end").strip()
            if not motivo:
                lbl_status.configure(text="⚠️ Informe o motivo do cancelamento.")
                return

            btn_confirmar.configure(state="disabled", text="Enviando...")
            lbl_status.configure(text="Assinando e enviando...", text_color="gray")
            popup.update()

            ok, msg = self.monitor.cancelar_nota(
                id_nota, chave_acesso, cnpj_prestador, motivo
            )

            if ok:
                popup.destroy()
                self._atualizar_lista()
            else:
                btn_confirmar.configure(state="normal",
                                        text="✅ Confirmar Cancelamento")
                lbl_status.configure(text=f"❌ {msg}", text_color="#c0392b")

        f_btns = ctk.CTkFrame(popup, fg_color="transparent")
        f_btns.pack(pady=5)

        btn_confirmar = ctk.CTkButton(
            f_btns, text="✅ Confirmar Cancelamento",
            width=210, height=40, fg_color="#c0392b", hover_color="#962d22",
            command=confirmar
        )
        btn_confirmar.pack(side="left", padx=10)

        ctk.CTkButton(f_btns, text="Voltar", width=100, height=40,
                      fg_color="gray", command=popup.destroy).pack(side="left")