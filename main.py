import customtkinter as ctk
import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog, simpledialog
import os
import sys
import json
import base64
import hmac
import hashlib
from datetime import datetime

# =========================================================================
# IMPORTAÇÃO DA CHAVE DE SEGURANÇA EXTERNA
# Certifique-se de que o arquivo "credenciais.py" existe na mesma pasta!
# =========================================================================
from credenciais import CHAVE_SECRETA

try:
    from PIL import Image, ImageTk

    TEM_PILLOW = True
except ImportError:
    TEM_PILLOW = False
    print("AVISO: Biblioteca 'Pillow' não instalada. As imagens podem não redimensionar corretamente.")
    print("Instale usando: pip install Pillow")


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    caminho = os.path.join(base_path, relative_path)
    if os.path.exists(caminho): return caminho
    return os.path.join(base_path, "assets", relative_path)


from contabil_modulo import ContabilModulo
from fiscal_modulo import FiscalModulo
from nfse_modulo import PortalNacionalModulo
from betha_modulo import EmissorBethaModulo

# Configuração Global do CustomTkinter
ctk.set_appearance_mode("System")  # Adapta-se ao tema do Windows (Light/Dark)
ctk.set_default_color_theme("blue")  # Tema de cores primárias


class SistemaUnificadoGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Automação Abentroth v5.7")
        self.root.geometry("1100x830")
        self.root.resizable(True, True)

        if getattr(sys, 'frozen', False):
            self.pasta_exe = os.path.dirname(sys.executable)
        else:
            self.pasta_exe = os.path.dirname(os.path.abspath(__file__))

        self.caminho_config = os.path.join(self.pasta_exe, "config_sistema.json")
        self.configuracoes = self.carregar_todas_configs()

        try:
            self.root.iconbitmap(resource_path("ico.ico"))
        except:
            pass

        # Substituição do Frame padrão pelo CTkFrame
        self.container = ctk.CTkFrame(self.root, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=10, pady=10)

        self.contabil = ContabilModulo(self)
        self.fiscal = FiscalModulo(self)
        self.nfse = PortalNacionalModulo(self)
        self.betha = EmissorBethaModulo(self)

        self.mostrar_menu_inicial()

    def carregar_imagem_ajustada(self, path_imagem, max_size=(300, 180)):
        if not TEM_PILLOW:
            return None

        if not os.path.exists(path_imagem):
            img = Image.new('RGB', max_size, color='#f0f0f0')
        else:
            try:
                img = Image.open(path_imagem)
            except Exception as e:
                print(f"Erro imagem: {e}")
                img = Image.new('RGB', max_size, color='#ffcccc')

        # O CustomTkinter faz o redimensionamento nativo e perfeito!
        return ctk.CTkImage(light_image=img, dark_image=img, size=max_size)

    def carregar_todas_configs(self):
        padrao = {
            "ultimo_caminho": os.path.join(self.pasta_exe, "saida de arquivos"),
            "pasta_jpype": "",
            "pasta_playwright": "",
            "chrome_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "velocidade": "1",
            "licenca": ""
        }
        if os.path.exists(self.caminho_config):
            try:
                with open(self.caminho_config, "r", encoding="utf-8") as f:
                    dados = json.load(f)
                    padrao.update(dados)
            except:
                pass
        return padrao

    def salvar_config(self, chave=None, valor=None):
        if chave and valor is not None:
            self.configuracoes[chave] = valor
        try:
            with open(self.caminho_config, "w", encoding="utf-8") as f:
                json.dump(self.configuracoes, f, indent=4)
        except:
            pass

    # =========================================================================
    # LÓGICA DE LICENCIAMENTO
    # =========================================================================
    def licenca_valida(self):
        chave = self.configuracoes.get("licenca", "")
        if not chave:
            return False

        try:
            texto_decodificado = base64.b64decode(chave.encode('utf-8')).decode('utf-8')
            partes = texto_decodificado.split('|')

            if len(partes) == 3 and partes[0] == "ABENTROTH":
                data_str = partes[1]
                assinatura_recebida = partes[2]

                texto_base = f"ABENTROTH|{data_str}"

                # USA A CHAVE DO ARQUIVO EXTERNO (credenciais.py)
                assinatura_calculada = hmac.new(CHAVE_SECRETA, texto_base.encode('utf-8'), hashlib.sha256).hexdigest()[
                    :16]

                if assinatura_recebida == assinatura_calculada:
                    data_validade = datetime.strptime(data_str, "%Y-%m-%d")
                    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

                    if hoje <= data_validade:
                        return True
                else:
                    # ==========================================================
                    # O SUSTO: O Lacre foi quebrado!
                    # ==========================================================
                    print("ALERTA: Tentativa de manipulação de licença detectada!")

                    from tkinter import messagebox
                    messagebox.showerror(
                        "🔒 VIOLAÇÃO DE SEGURANÇA DETECTADA",
                        "⚠️ ALERTA CRÍTICO DE SISTEMA ⚠️\n\n"
                        "O sistema detectou uma tentativa de manipulação, alteração ou falsificação da chave de licença.\n\n"
                        "A integridade do software foi comprometida. O acesso aos módulos de automação foi severamente bloqueado por motivos de segurança.\n\n"
                        "Se este erro persistir, o administrador será notificado com o log de atividades."
                    )
                    return False

        except Exception:
            return False

        return False

    def verificar_acesso_modulo(self, comando_modulo):
        if self.licenca_valida():
            comando_modulo()
        else:
            self.mostrar_aviso_bloqueio()

    def mostrar_aviso_bloqueio(self):
        aviso = ctk.CTkToplevel(self.root)
        aviso.title("Acesso Bloqueado")
        aviso.geometry("400x180")
        aviso.resizable(False, False)

        # Truque para forçar o ícone em janelas CTkToplevel
        try:
            aviso.after(200, lambda: aviso.iconbitmap(resource_path("ico.ico")))
        except:
            pass

        aviso.transient(self.root)
        aviso.grab_set()

        f_msg = ctk.CTkFrame(aviso, fg_color="transparent")
        f_msg.pack(pady=20)
        ctk.CTkLabel(f_msg, text="❌ Licença expirada ou não cadastrada.", font=("Arial", 14, "bold"),
                     text_color="#d32f2f").pack()
        ctk.CTkLabel(f_msg, text="Por favor, insira uma nova chave para continuar.", font=("Arial", 12)).pack(pady=5)

        f_btns = ctk.CTkFrame(aviso, fg_color="transparent")
        f_btns.pack(pady=10)

        def acao_alterar():
            aviso.destroy()
            self.abrir_tela_licenca()

        ctk.CTkButton(f_btns, text="Fechar", command=aviso.destroy, width=100, fg_color="gray",
                      hover_color="darkgray").pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(f_btns, text="Alterar Chave", command=acao_alterar, width=120, fg_color="#242424",
                      hover_color="#1a1a1a").pack(side=tk.LEFT, padx=10)

    def abrir_tela_licenca(self):
        janela = ctk.CTkToplevel(self.root)
        janela.title("Gerenciador de Licença")
        janela.geometry("450x350")
        janela.resizable(False, False)

        try:
            janela.after(200, lambda: janela.iconbitmap(resource_path("ico.ico")))
        except:
            pass

        janela.transient(self.root)
        janela.grab_set()

        f_status = ctk.CTkFrame(janela, fg_color="transparent")
        f_status.pack(pady=20)

        if self.licenca_valida():
            try:
                chave = self.configuracoes.get("licenca", "")
                texto = base64.b64decode(chave.encode('utf-8')).decode('utf-8')
                data_str = texto.split('|')[1]
                data_br = datetime.strptime(data_str, "%Y-%m-%d").strftime("%d/%m/%Y")
                ctk.CTkLabel(f_status, text="✅ Status: ATIVA", font=("Arial", 16, "bold"), text_color="#228B22").pack()
                ctk.CTkLabel(f_status, text=f"Válida até: {data_br}", font=("Arial", 14)).pack()
            except:
                pass
        else:
            ctk.CTkLabel(f_status, text="❌ Status: EXPIRADA / INVÁLIDA", font=("Arial", 16, "bold"),
                         text_color="#d32f2f").pack()

        f_input = ctk.CTkFrame(janela, fg_color="transparent")
        f_input.pack(pady=10)
        ctk.CTkLabel(f_input, text="Insira a nova chave de ativação:", font=("Arial", 12)).pack()

        var_chave = tk.StringVar()
        ent_chave = ctk.CTkEntry(f_input, textvariable=var_chave, width=350, height=35, font=("Arial", 12),
                                 justify="center")
        ent_chave.pack(pady=10)

        def salvar_nova_licenca():
            nova = var_chave.get().strip()
            if nova:
                self.salvar_config("licenca", nova)
                if self.licenca_valida():
                    messagebox.showinfo("Sucesso", "Licença ativada com sucesso!")
                    janela.destroy()
                else:
                    messagebox.showerror("Erro", "A chave inserida é inválida ou já expirou.")
            else:
                messagebox.showwarning("Atenção", "Insira uma chave válida.")

        ctk.CTkButton(f_input, text="Ativar Licença", command=salvar_nova_licenca, fg_color="#228B22",
                      hover_color="#1e7a1e", font=("Arial", 14, "bold"), width=180, height=40).pack(pady=10)

    # =========================================================================

    def mostrar_info_sistema(self):
        janela = ctk.CTkToplevel(self.root)
        janela.title("Sobre o Sistema")
        janela.geometry("450x300")
        janela.resizable(False, False)

        try:
            janela.after(200, lambda: janela.iconbitmap(resource_path("ico.ico")))
        except:
            pass

        janela.transient(self.root)
        janela.grab_set()

        info_texto = (
            "Autor: Guilherme Abentroth\n"
            "Versão: 5.7\n"
            "Data da Versão: 28/02/2026\n\n"
            "Notas da Versão:\n"
            "1. Novo Design Moderno (CustomTkinter).\n"
            "2. Adicionado bloqueio por licenciamento seguro.\n"
            "3. Módulo emissor NFSE e C6 Bank implementados.\n"
        )

        f_info = ctk.CTkFrame(janela, fg_color="transparent")
        f_info.pack(pady=20, padx=20, fill="both", expand=True)

        ctk.CTkLabel(f_info, text="Automação Abentroth", font=("Arial", 18, "bold")).pack(pady=5)
        ctk.CTkLabel(f_info, text=info_texto, font=("Arial", 12), justify="left").pack(pady=10)

        ctk.CTkButton(f_info, text="Fechar", command=janela.destroy, width=120, fg_color="#242424",
                      hover_color="#1a1a1a").pack(pady=10)

    def abrir_tela_config(self):
        senha = simpledialog.askstring("Restrito", "Digite a senha de admin:", show='*')
        if senha != "579499":
            messagebox.showerror("Erro", "Senha incorreta!")
            return

        janela = ctk.CTkToplevel(self.root)
        janela.title("Configurações")
        janela.geometry("800x400")

        try:
            janela.after(200, lambda: janela.iconbitmap(resource_path("ico.ico")))
        except:
            pass

        janela.transient(self.root)
        janela.grab_set()

        f_main = ctk.CTkFrame(janela)
        f_main.pack(fill="both", expand=True, padx=20, pady=20)

        def criar_linha(txt, chave):
            f = ctk.CTkFrame(f_main, fg_color="transparent")
            f.pack(fill="x", pady=10)

            ctk.CTkLabel(f, text=txt, font=("Arial", 12, "bold"), width=150, anchor="w").pack(side=tk.LEFT)

            var = tk.StringVar(value=self.configuracoes.get(chave, ""))
            ctk.CTkEntry(f, textvariable=var, width=450).pack(side=tk.LEFT, padx=10)

            def b():
                p = filedialog.askopenfilename() if "chrome" in chave else filedialog.askdirectory()
                if p: var.set(p)

            def ok(): self.salvar_config(chave, var.get()); messagebox.showinfo("OK", "Salvo!")

            ctk.CTkButton(f, text="...", command=b, width=40).pack(side=tk.LEFT, padx=5)
            ctk.CTkButton(f, text="OK", command=ok, width=50).pack(side=tk.LEFT)

        def criar_vel():
            f = ctk.CTkFrame(f_main, fg_color="transparent")
            f.pack(fill="x", pady=10)
            ctk.CTkLabel(f, text="Velocidade:", font=("Arial", 12, "bold"), width=150, anchor="w").pack(side=tk.LEFT)

            var = tk.StringVar(value=self.configuracoes.get("velocidade", "1"))
            op = ctk.CTkOptionMenu(f, variable=var, values=["1", "2", "3"], width=100)
            op.pack(side=tk.LEFT, padx=10)

            def save_vel():
                self.salvar_config("velocidade", var.get())
                messagebox.showinfo("OK", "Salvo!")

            ctk.CTkButton(f, text="OK", command=save_vel, width=50).pack(side=tk.LEFT, padx=105)

        criar_linha("Pasta JPype:", "pasta_jpype")
        criar_linha("Pasta Playwright:", "pasta_playwright")
        criar_linha("Chrome Path:", "chrome_path")
        criar_vel()

    def log_msg(self, mensagem, tipo="info", divisor=False):
        if hasattr(self, 'txt_log') and self.txt_log.winfo_exists():
            timestamp = datetime.now().strftime('%H:%M:%S')
            self.txt_log.config(state='normal')
            if divisor: self.txt_log.insert(tk.END, "\n" + "=" * 90 + "\n")
            tag = tipo if tipo in ["erro", "sucesso"] else "info"
            self.txt_log.tag_config("erro", foreground="red")
            self.txt_log.tag_config("sucesso", foreground="green")
            self.txt_log.insert(tk.END, f"[{timestamp}] {mensagem}\n", tag)
            self.txt_log.see(tk.END)
            self.txt_log.config(state='disabled')
            self.root.update()

    def limpar_tela(self):
        for widget in self.container.winfo_children(): widget.destroy()

    def carregar_logo(self, parent):
        path_logo = resource_path("logo.png")
        if os.path.exists(path_logo) and TEM_PILLOW:
            try:
                img_pil = Image.open(path_logo)
                w, h = img_pil.size
                nova_largura, nova_altura = int(w / 3), int(h / 3)

                self.img_logo = ctk.CTkImage(light_image=img_pil, dark_image=img_pil, size=(nova_largura, nova_altura))

                ctk.CTkLabel(parent, text="", image=self.img_logo).pack()
            except Exception as e:
                ctk.CTkLabel(parent, text="SISTEMA AUTOMAÇÃO", font=("Arial", 24, "bold")).pack()
        else:
            ctk.CTkLabel(parent, text="SISTEMA AUTOMAÇÃO", font=("Arial", 24, "bold")).pack()

    def mostrar_menu_inicial(self):
        self.limpar_tela()

        # Barra de Menu Topo
        f_top = ctk.CTkFrame(self.container, fg_color="transparent")
        f_top.pack(fill="x", pady=10)

        ctk.CTkButton(f_top, text="🔑 Licença", command=self.abrir_tela_licenca,
                      width=100, fg_color="transparent", border_width=1, text_color=("black", "white")).pack(
            side="right", padx=5)
        ctk.CTkButton(f_top, text="⚙ Config", command=self.abrir_tela_config,
                      width=80, fg_color="transparent", text_color=("black", "white")).pack(side="right", padx=5)
        ctk.CTkButton(f_top, text="ℹ️ Info", command=self.mostrar_info_sistema,
                      width=80, fg_color="transparent", text_color=("black", "white")).pack(side="right", padx=5)

        # Logo
        f_l = ctk.CTkFrame(self.container, fg_color="transparent")
        f_l.pack(pady=40)
        self.carregar_logo(f_l)

        # Grid Central para os Módulos
        f_b = ctk.CTkFrame(self.container, fg_color="transparent")
        f_b.pack(pady=50)

        ctk.CTkButton(f_b, text="FISCAL", command=lambda: self.verificar_acesso_modulo(self.tela_fiscal),
                      width=220, height=80, font=("Arial", 20, "bold"), fg_color="#228B22", hover_color="#1e7a1e").grid(
            row=0, column=0, padx=20, pady=20)

        ctk.CTkButton(f_b, text="CONTÁBIL", command=lambda: self.verificar_acesso_modulo(self.tela_contabil),
                      width=220, height=80, font=("Arial", 20, "bold"), fg_color="#005A9C", hover_color="#00467a").grid(
            row=0, column=1, padx=20, pady=20)

        ctk.CTkButton(f_b, text="PORTAL NACIONAL", command=lambda: self.verificar_acesso_modulo(self.nfse.tela_nfse),
                      width=220, height=80, font=("Arial", 20, "bold"), fg_color="#f39200", hover_color="#cc7a00").grid(
            row=0, column=2, padx=20, pady=20)

        ctk.CTkButton(f_b, text="EMISSOR NFSE",
                      command=lambda: self.verificar_acesso_modulo(self.betha.tela_emissor_betha),
                      width=220, height=80, font=("Arial", 20, "bold"), fg_color="#8e44ad", hover_color="#732d91").grid(
            row=0, column=3, padx=20, pady=20)

        # Rodapé
        ctk.CTkLabel(self.container, text="Powered by: Guilherme Abentroth", font=("Arial", 12)).pack(side=tk.BOTTOM,
                                                                                                      anchor="w",
                                                                                                      padx=20, pady=20)

    # -------------------------------------------------------------------------
    # TELAS PADRONIZADAS COM CUSTOM TKINTER
    # -------------------------------------------------------------------------
    def construir_tela_unico_modelo(self, nome_banco, nome_imagem, cor_titulo, funcao_backend):
        self.limpar_tela()

        f_top = ctk.CTkFrame(self.container, fg_color="transparent")
        f_top.pack(pady=20)
        ctk.CTkLabel(f_top, text=f"Importação {nome_banco}", font=("Arial", 22, "bold"), text_color=cor_titulo).pack()
        ctk.CTkLabel(f_top, text="Clique na imagem abaixo para selecionar o arquivo e iniciar.",
                     font=("Arial", 12)).pack()

        def bridge(lista):
            self.contabil.gerar_ofx(self.log_msg, lista)

        f_img = ctk.CTkFrame(self.container, fg_color="transparent")
        f_img.pack(pady=20)

        path_img = resource_path(nome_imagem)
        self.img_temp = self.carregar_imagem_ajustada(path_img, max_size=(350, 250))

        btn_img = ctk.CTkButton(
            f_img,
            text="",
            image=self.img_temp,
            command=lambda: funcao_backend(self.log_msg, bridge),
            fg_color="transparent",
            hover_color="#e0e0e0"
        )
        btn_img.pack()

        ctk.CTkLabel(f_img, text=f"Modelo Padrão {nome_banco}", font=("Arial", 12, "bold")).pack(pady=10)

        f_log = ctk.CTkFrame(self.container)
        f_log.pack(fill="both", expand=True, padx=40, pady=10)
        ctk.CTkLabel(f_log, text="Log de Processamento:", font=("Arial", 12, "bold")).pack(anchor="w", padx=10, pady=5)

        self.txt_log = scrolledtext.ScrolledText(f_log, width=120, height=10, state='disabled', bg="#1e1e1e",
                                                 fg="white", font=("Consolas", 10))
        self.txt_log.pack(padx=10, pady=5, fill="both", expand=True)

        f_btns = ctk.CTkFrame(self.container, fg_color="transparent")
        f_btns.pack(pady=20)
        ctk.CTkButton(f_btns, text="Voltar", command=self.tela_contabil, fg_color="gray", hover_color="darkgray",
                      width=150, height=40).pack()

    # (AS TELAS DE ESCOLHA DE IMAGEM ÚNICA FICAM IGUAIS, APENAS O WRAPPER FOI ATUALIZADO)
    def tela_escolha_stone(self):
        self.construir_tela_unico_modelo("Stone", "STONE.png", "#00A868", self.contabil.fluxo_stone)

    def tela_escolha_pagbank(self):
        self.construir_tela_unico_modelo("PagBank", "PAGBANK.png", "#8BC34A", self.contabil.fluxo_pagbank)

    def tela_escolha_sicredi(self):
        self.construir_tela_unico_modelo("Sicredi", "SICREDI.png", "#32BC43", self.contabil.fluxo_sicredi)

    def tela_escolha_ailos(self):
        self.construir_tela_unico_modelo("Ailos", "AILOS.png", "#005A9C", self.contabil.fluxo_ailos)

    def tela_escolha_ifood(self):
        self.construir_tela_unico_modelo("iFood", "IFOOD.png", "#EA1D2C", self.contabil.fluxo_ifood)

    def tela_escolha_cresol(self):
        self.construir_tela_unico_modelo("Cresol", "CRESOL.png", "#006B3F", self.contabil.fluxo_cresol)

    def tela_escolha_c6(self):
        self.construir_tela_unico_modelo("C6 Bank", "C6.png", "#242424", self.contabil.fluxo_c6)

    # -------------------------------------------------------------------------
    # TELAS MULTI-IMAGEM (CAIXA, SANTANDER, BB, SICOOB)
    # -------------------------------------------------------------------------
    def criar_tela_multi_modelos(self, nome_banco, cor_titulo, funcoes):
        self.limpar_tela()

        f_top = ctk.CTkFrame(self.container, fg_color="transparent")
        f_top.pack(pady=15)
        ctk.CTkLabel(f_top, text=f"Selecione o Modelo do Extrato {nome_banco}", font=("Arial", 20, "bold"),
                     text_color=cor_titulo).pack()
        ctk.CTkLabel(f_top, text="Clique na imagem para iniciar o processamento", font=("Arial", 12)).pack()

        f_imgs = ctk.CTkFrame(self.container, fg_color="transparent")
        f_imgs.pack(pady=10)

        col = 0
        row = 0
        self._img_refs = []

        def bridge(lista):
            self.contabil.gerar_ofx(self.log_msg, lista)

        for cfg in funcoes:
            f_op = ctk.CTkFrame(f_imgs, fg_color="transparent")
            f_op.grid(row=row, column=col, padx=20, pady=10)

            img_ctk = self.carregar_imagem_ajustada(resource_path(cfg["img"]), max_size=(250, 150))
            self._img_refs.append(img_ctk)

            cmd = lambda c=cfg["cmd"]: c(self.log_msg, bridge)

            btn = ctk.CTkButton(f_op, text="", image=img_ctk, command=cmd, fg_color="transparent",
                                hover_color="#e0e0e0")
            btn.pack()

            ctk.CTkLabel(f_op, text=cfg["texto"], font=("Arial", 12, "bold")).pack(pady=5)

            col += 1
            if col > 1:
                col = 0
                row += 1

        f_log = ctk.CTkFrame(self.container)
        f_log.pack(fill="both", expand=True, padx=40, pady=10)
        ctk.CTkLabel(f_log, text="Log de Processamento:", font=("Arial", 12, "bold")).pack(anchor="w", padx=10, pady=5)

        self.txt_log = scrolledtext.ScrolledText(f_log, width=120, height=8, state='disabled', bg="#1e1e1e", fg="white",
                                                 font=("Consolas", 10))
        self.txt_log.pack(padx=10, pady=5, fill="both", expand=True)

        ctk.CTkButton(self.container, text="Voltar", command=self.tela_contabil, fg_color="gray",
                      hover_color="darkgray", width=150, height=40).pack(pady=15)

    def tela_escolha_caixa(self):
        configs = [
            {"texto": "Caixa V1 (Antigo)", "img": "CAIXA.png", "cmd": self.contabil.fluxo_caixa_v1},
            {"texto": "Caixa V2 (Horizontal)", "img": "CAIXA2.png", "cmd": self.contabil.fluxo_caixa_v2_horizontal},
            {"texto": "Caixa V2 (Vertical)", "img": "CAIXA2.png", "cmd": self.contabil.fluxo_caixa_v2_vertical},
            {"texto": "Caixa V3 (D/C)", "img": "CAIXA3.png", "cmd": self.contabil.fluxo_caixa_v3}
        ]
        self.criar_tela_multi_modelos("CAIXA", "#005CA9", configs)

    def tela_escolha_santander(self):
        configs = [
            {"texto": "Santander (Padrão)", "img": "SANTANDER.png", "cmd": self.contabil.fluxo_santander_v1},
            {"texto": "Santander (Empresas)", "img": "SANTANDER2.png", "cmd": self.contabil.fluxo_santander_v2}
        ]
        self.criar_tela_multi_modelos("SANTANDER", "#ec0000", configs)

    def tela_escolha_bb(self):
        configs = [
            {"texto": "BB Modelo 1 (Padrão)", "img": "modelo_bb1.png", "cmd": self.contabil.fluxo_bb_v1},
            {"texto": "BB Modelo 2 (Digital)", "img": "modelo_bb2.png", "cmd": self.contabil.fluxo_bb_v2}
        ]
        self.criar_tela_multi_modelos("BANCO DO BRASIL", "#fdb913", configs)

    def tela_escolha_sicoob(self):
        configs = [
            {"texto": "Sicoob Celular (App)", "img": "sicoob_celular.png", "cmd": self.contabil.fluxo_sicoob_celular},
            {"texto": "Sicoob PDF (Desktop)", "img": "sicoob_pdf.png", "cmd": self.contabil.fluxo_sicoob_pdf}
        ]
        self.criar_tela_multi_modelos("SICOOB", "#00ae9d", configs)

    # -------------------------------------------------------------------------
    # TELA PRINCIPAL CONTÁBIL
    # -------------------------------------------------------------------------
    def tela_contabil(self):
        self.limpar_tela()

        f_l = ctk.CTkFrame(self.container, fg_color="transparent")
        f_l.pack(pady=10)
        self.carregar_logo(f_l)

        # Log ao topo
        f_log_area = ctk.CTkFrame(self.container)
        f_log_area.pack(fill="x", padx=40, pady=10)
        ctk.CTkLabel(f_log_area, text="Log de Processamento:", font=("Arial", 12, "bold")).pack(anchor="w", padx=10)
        self.txt_log = scrolledtext.ScrolledText(f_log_area, width=125, height=8, state='disabled', bg="#1e1e1e",
                                                 fg="white", font=("Consolas", 10))
        self.txt_log.pack(padx=10, pady=5, fill="x")

        f_b = ctk.CTkFrame(self.container, fg_color="transparent")
        f_b.pack(pady=20)

        # Estilo dos botões menores
        btn_w = 140
        btn_h = 40
        f_font = ("Arial", 12, "bold")

        f_b1 = ctk.CTkFrame(f_b, fg_color="transparent")
        f_b1.pack(pady=10)
        ctk.CTkButton(f_b1, text="Banco do Brasil", command=self.tela_escolha_bb, width=btn_w, height=btn_h,
                      font=f_font, fg_color="#fdb913", hover_color="#c99106").pack(side="left", padx=10)
        ctk.CTkButton(f_b1, text="Caixa", command=self.tela_escolha_caixa, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#005CA9", hover_color="#00407a").pack(side="left", padx=10)
        ctk.CTkButton(f_b1, text="Santander", command=self.tela_escolha_santander, width=btn_w, height=btn_h,
                      font=f_font, fg_color="#ec0000", hover_color="#b30000").pack(side="left", padx=10)
        ctk.CTkButton(f_b1, text="Sicredi", command=self.tela_escolha_sicredi, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#32BC43", hover_color="#248a31").pack(side="left", padx=10)

        f_b2 = ctk.CTkFrame(f_b, fg_color="transparent")
        f_b2.pack(pady=10)
        ctk.CTkButton(f_b2, text="Sicoob", command=self.tela_escolha_sicoob, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#00ae9d", hover_color="#008073").pack(side="left", padx=10)
        ctk.CTkButton(f_b2, text="Ailos", command=self.tela_escolha_ailos, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#005A9C", hover_color="#003d6b").pack(side="left", padx=10)
        ctk.CTkButton(f_b2, text="Stone", command=self.tela_escolha_stone, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#00A868", hover_color="#007a4c").pack(side="left", padx=10)
        ctk.CTkButton(f_b2, text="PagBank", command=self.tela_escolha_pagbank, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#8BC34A", hover_color="#649131").pack(side="left", padx=10)

        f_b3 = ctk.CTkFrame(f_b, fg_color="transparent")
        f_b3.pack(pady=10)
        ctk.CTkButton(f_b3, text="iFood", command=self.tela_escolha_ifood, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#EA1D2C", hover_color="#b3121f").pack(side="left", padx=10)
        ctk.CTkButton(f_b3, text="Cresol", command=self.tela_escolha_cresol, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#006B3F", hover_color="#004529").pack(side="left", padx=10)
        ctk.CTkButton(f_b3, text="C6 Bank", command=self.tela_escolha_c6, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#242424", hover_color="#141414").pack(side="left", padx=10)
        ctk.CTkButton(f_b3, text="Excel > OFX", command=lambda: self.contabil.gerar_ofx(self.log_msg), width=btn_w,
                      height=btn_h, font=f_font, fg_color="#7f8c8d", hover_color="#576162").pack(side="left", padx=10)

        f_b4 = ctk.CTkFrame(f_b, fg_color="transparent")
        f_b4.pack(pady=20)
        ctk.CTkButton(f_b4, text="Voltar Menu", command=self.mostrar_menu_inicial, fg_color="gray",
                      hover_color="darkgray", width=200, height=40).pack(side="left", padx=10)

    # -------------------------------------------------------------------------
    # TELA FISCAL
    # -------------------------------------------------------------------------
    def tela_fiscal(self):
        self.limpar_tela()

        f_l = ctk.CTkFrame(self.container, fg_color="transparent")
        f_l.pack(pady=10)
        self.carregar_logo(f_l)

        # Card de Seleção de Pasta
        f_c = ctk.CTkFrame(self.container)
        f_c.pack(fill="x", padx=40, pady=20)

        ctk.CTkLabel(f_c, text="Pasta de Saída:", font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=15, pady=15)
        self.entry_saida = ctk.CTkEntry(f_c, font=("Arial", 12), width=500)
        self.entry_saida.pack(side=tk.LEFT, padx=10)
        self.entry_saida.insert(0, self.configuracoes.get("ultimo_caminho", ""))

        ctk.CTkButton(f_c, text="Procurar", command=self.selecionar_p_f, width=100).pack(side=tk.LEFT, padx=15)

        # Área de Log
        f_log_area = ctk.CTkFrame(self.container, fg_color="transparent")
        f_log_area.pack(fill="both", expand=True, padx=40, pady=5)
        self.txt_log = scrolledtext.ScrolledText(f_log_area, width=125, height=15, state='disabled', bg="#1e1e1e",
                                                 fg="white", font=("Consolas", 10))
        self.txt_log.pack(fill="both", expand=True)

        # Botões de Ação
        f_btns = ctk.CTkFrame(self.container, fg_color="transparent")
        f_btns.pack(pady=20)
        ctk.CTkButton(f_btns, text="▶ INICIAR PROCESSAMENTO FISCAL", command=self.exec_f_logic,
                      fg_color="#228B22", hover_color="#1e7a1e", font=("Arial", 14, "bold"), height=50, width=350).pack(
            side="left", padx=20)
        ctk.CTkButton(f_btns, text="Voltar Menu", command=self.mostrar_menu_inicial,
                      fg_color="gray", hover_color="darkgray", font=("Arial", 14), height=50, width=150).pack(
            side="left")

    def selecionar_p_f(self):
        p = filedialog.askdirectory()
        if p:
            self.entry_saida.delete(0, tk.END)
            self.entry_saida.insert(0, p)

    def exec_f_logic(self):
        path_atual = self.entry_saida.get().strip()
        if not path_atual:
            messagebox.showwarning("Atenção", "Selecione uma pasta de saída primeiro.")
            return

        resp = messagebox.askyesno("Confirmar", f"Salvar arquivos em:\n{path_atual}\n\nConfirma?")
        if not resp:
            novo = filedialog.askdirectory()
            if novo:
                self.entry_saida.delete(0, tk.END)
                self.entry_saida.insert(0, novo)
                path_atual = novo
            else:
                return

        self.salvar_config("ultimo_caminho", path_atual)
        self.fiscal.executar_fiscal(path_atual, self.log_msg)
        messagebox.showinfo("Sucesso", "Concluído.")


if __name__ == "__main__":
    root = ctk.CTk()
    app = SistemaUnificadoGUI(root)
    root.mainloop()