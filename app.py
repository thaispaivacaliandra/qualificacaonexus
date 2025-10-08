from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime
import uuid
import requests
import json
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Importações para PostgreSQL
try:
    import psycopg2
    import psycopg2.extras
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

# Carrega variáveis de ambiente
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev_secret_key_change_in_production')
CORS(app)

# Configurações
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
os.makedirs('/tmp', exist_ok=True)
DATABASE_URL = os.getenv('DATABASE_URL', '/tmp/leads.db')

class LeadManager:
    """Gerencia operações de banco de dados para leads - SQLite e PostgreSQL"""
    
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.is_postgres = db_url.startswith('postgresql://') or db_url.startswith('postgres://')
        
        if self.is_postgres and not POSTGRES_AVAILABLE:
            raise ImportError("psycopg2 não está instalado. Execute: pip install psycopg2-binary")
        
        self.init_database()
    
    def get_connection(self):
        """Retorna conexão apropriada (SQLite ou PostgreSQL)"""
        if self.is_postgres:
            # Corrige URL do postgres para postgresql se necessário
            db_url = self.db_url.replace('postgres://', 'postgresql://', 1)
            return psycopg2.connect(db_url)
        else:
            return sqlite3.connect(self.db_url)
    
    def init_database(self):
        """Inicializa as tabelas do banco"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                # PostgreSQL syntax
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS leads (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT UNIQUE NOT NULL,
                        nome TEXT,
                        empresa TEXT,
                        segmento TEXT,
                        problema TEXT,
                        investimento_atual TEXT,
                        telefone TEXT,
                        email TEXT,
                        qualificado BOOLEAN DEFAULT FALSE,
                        conversa_completa TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS mensagens (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Criar índices para performance
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_leads_session ON leads(session_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_mensagens_session ON mensagens(session_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_mensagens_timestamp ON mensagens(timestamp)')
                
            else:
                # SQLite syntax (desenvolvimento)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS leads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT UNIQUE NOT NULL,
                        nome TEXT,
                        empresa TEXT,
                        segmento TEXT,
                        problema TEXT,
                        investimento_atual TEXT,
                        telefone TEXT,
                        email TEXT,
                        qualificado BOOLEAN DEFAULT FALSE,
                        conversa_completa TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS mensagens (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
            
            conn.commit()
            conn.close()
            print(f"✅ Banco {'PostgreSQL' if self.is_postgres else 'SQLite'} inicializado com sucesso")
            
        except Exception as e:
            print(f"❌ Erro ao inicializar banco: {e}")
            raise
    
    def create_lead(self, session_id: str) -> bool:
        """Cria um novo lead na base"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                cursor.execute(
                    'INSERT INTO leads (session_id) VALUES (%s) ON CONFLICT (session_id) DO NOTHING',
                    (session_id,)
                )
            else:
                cursor.execute('INSERT OR IGNORE INTO leads (session_id) VALUES (?)', (session_id,))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Erro ao criar lead: {e}")
            return False
    
    def update_lead(self, session_id: str, data: Dict) -> bool:
        """Atualiza dados do lead"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Campos permitidos
            allowed_fields = ['nome', 'empresa', 'segmento', 'problema', 'investimento_atual', 
                            'telefone', 'email', 'qualificado', 'conversa_completa']
            
            # Monta query dinâmica baseada nos campos fornecidos
            fields = []
            values = []
            for key, value in data.items():
                if key in allowed_fields:
                    if self.is_postgres:
                        fields.append(f"{key} = %s")
                    else:
                        fields.append(f"{key} = ?")
                    values.append(value)
            
            if fields:
                if self.is_postgres:
                    query = f"UPDATE leads SET {', '.join(fields)} WHERE session_id = %s"
                else:
                    query = f"UPDATE leads SET {', '.join(fields)} WHERE session_id = ?"
                values.append(session_id)
                cursor.execute(query, values)
                conn.commit()
            
            conn.close()
            return True
        except Exception as e:
            print(f"Erro ao atualizar lead: {e}")
            return False
    
    def save_message(self, session_id: str, role: str, content: str) -> bool:
        """Salva uma mensagem no histórico"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                cursor.execute(
                    'INSERT INTO mensagens (session_id, role, content) VALUES (%s, %s, %s)',
                    (session_id, role, content)
                )
            else:
                cursor.execute(
                    'INSERT INTO mensagens (session_id, role, content) VALUES (?, ?, ?)',
                    (session_id, role, content)
                )
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Erro ao salvar mensagem: {e}")
            return False
    
    def get_conversation_history(self, session_id: str) -> List[Dict]:
        """Recupera histórico da conversa"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                cursor.execute(
                    'SELECT role, content, timestamp FROM mensagens WHERE session_id = %s ORDER BY timestamp ASC',
                    (session_id,)
                )
            else:
                cursor.execute(
                    'SELECT role, content, timestamp FROM mensagens WHERE session_id = ? ORDER BY timestamp ASC',
                    (session_id,)
                )
            
            messages = []
            for row in cursor.fetchall():
                messages.append({
                    'role': row[0],
                    'content': row[1],
                    'timestamp': str(row[2])
                })
            conn.close()
            return messages
        except Exception as e:
            print(f"Erro ao recuperar histórico: {e}")
            return []
    
    def get_leads_stats(self) -> Dict:
        """Retorna estatísticas dos leads"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_leads,
                        COUNT(CASE WHEN qualificado = true THEN 1 END) as leads_qualificados,
                        COUNT(CASE WHEN nome IS NOT NULL THEN 1 END) as leads_com_nome,
                        COUNT(CASE WHEN email IS NOT NULL THEN 1 END) as leads_com_email
                    FROM leads
                ''')
            else:
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_leads,
                        COUNT(CASE WHEN qualificado = 1 THEN 1 END) as leads_qualificados,
                        COUNT(CASE WHEN nome IS NOT NULL THEN 1 END) as leads_com_nome,
                        COUNT(CASE WHEN email IS NOT NULL THEN 1 END) as leads_com_email
                    FROM leads
                ''')
            
            row = cursor.fetchone()
            conn.close()
            
            return {
                'total_leads': row[0],
                'leads_qualificados': row[1],
                'leads_com_nome': row[2],
                'leads_com_email': row[3],
                'taxa_qualificacao': round((row[1] / row[0] * 100) if row[0] > 0 else 0, 1)
            }
        except Exception as e:
            print(f"Erro ao buscar estatísticas: {e}")
            return {'total_leads': 0, 'leads_qualificados': 0, 'leads_com_nome': 0, 'leads_com_email': 0, 'taxa_qualificacao': 0}

class SDRChatbot:
    """Chatbot SDR para qualificação de leads"""
    
    def __init__(self, groq_api_key: str):
        self.api_key = groq_api_key
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        
        # Prompt base do SDR
        self.system_prompt = """
# Script SDR Completo - Qualificação Natural + Oportunidades em 5 Minutos

## SEU PERFIL:
- Vendedor nato: direto, sem enrolação
- Data-driven: usa estatísticas como arma de persuasão
- Consultivo: eleva o nível de consciência do prospect
- Focado em ROI: sempre conecta problemas a perdas financeiras
- **Identificador de oportunidades**: sempre mostra gaps concretos
- Personalizado: sempre usa o nome da pessoa e adapta a abordagem
- **CONVERSACIONAL**: uma pergunta por vez, construindo rapport

## POSICIONAMENTO DO GUSTAVO:
"Especialista em Aceleração de Negócios que une Web Design Estratégico + Análise de Performance + Automação + BI para gerar resultados reais e mensuráveis."

## DIFERENCIAIS:
- Visão 360º: não entrega só site, mas ecossistema completo
- Métricas que importam: ROI, custo por cliente, LTV
- Diagnóstico profundo antes de qualquer proposta
- Dashboards estratégicos personalizados
- Automações humanizadas com integrações inteligentes
- **Identifica oportunidades em tempo real durante a conversa**

## BADGES DISPONÍVEIS:
**Como posso ajudar?**
Especialista em aceleração digital. Vamos descobrir como turbinar seus resultados online.

**Medir ROI digital**
Saiba exatamente quanto cada canal retorna

**Automatizar vendas**
Sistemas que vendem 24/7

**Melhorar performance**
Identifique oportunidades de crescimento no seu digital

**Tracking comportamental**
Veja exatamente o que seus clientes fazem até comprar

## CENÁRIOS DE ENTRADA:

### OPÇÃO A - ENTRADA PELOS BADGES
**Quando o prospect clica em um badge específico, adapte a abertura:**

**Badge "Como posso ajudar?":**
- "Oi! Qual seu nome?"
- *[Após resposta]* "[Nome], vi que você quer saber como posso ajudar. Me conta um pouco sobre seu negócio?"

**Badge "Medir ROI digital":**
- "Oi! Qual seu nome?"
- *[Após resposta]* "[Nome], vi que você quer medir ROI digital. Atualmente você consegue saber quanto cada canal retorna?"

**Badge "Automatizar vendas":**
- "Oi! Qual seu nome?" 
- *[Após resposta]* "[Nome], interessante que você quer automatizar vendas. Hoje vocês vendem mais manual ou já tem alguma automação?"

**Badge "Melhorar performance":**
- "Oi! Qual seu nome?"
- *[Após resposta]* "[Nome], você quer melhorar performance. Qual métrica você mais acompanha hoje?"

**Badge "Tracking comportamental":**
- "Oi! Qual seu nome?"
- *[Após resposta]* "[Nome], tracking comportamental é fundamental! Você consegue ver o que seus clientes fazem no site hoje?"

### OPÇÃO B - ENTRADA GERAL
**Quando não há contexto específico:**
- "Oi! Qual seu nome?"
- *[Após resposta]* "[Nome], você já conhece nosso trabalho ou é primeira vez que ouve falar da gente?"

**Respostas adaptadas:**

**Se JÁ CONHECE:**
- "[Nome], que bom te encontrar aqui! Já que você conhece nosso trabalho, qual parte mais chamou sua atenção?"

**Se NÃO CONHECE:**
- "[Nome], perfeito! Deixa eu te explicar rapidamente: ajudo empresas a transformar visitantes em clientes usando dados reais. Qual é o seu negócio?"

**Se BUSCA ALGO ESPECÍFICO:**
- "[Nome], entendi que você está procurando [serviço específico]. Antes de tudo, me conta: qual o maior gargalo que está enfrentando com isso?"

## FLUXO DE QUALIFICAÇÃO NATURAL:

### ETAPA 1 - CONTEXTUALIZAÇÃO BASEADA NA ENTRADA
**Use as respostas adaptadas acima conforme o cenário**

### ETAPA 2 - DESCOBERTA PROGRESSIVA
**Baseado na resposta da etapa anterior, faça UMA pergunta contextualizada:**

**Para quem clicou "Medir ROI digital":**
- "[Nome], me conta: de todos os canais que você usa (site, redes, anúncios), qual você sente que traz mais resultado?"

**Para quem clicou "Automatizar vendas":**
- "[Nome], atualmente como funciona seu processo de vendas? Mais manual ou vocês já automatizaram alguma parte?"

**Para quem clicou "Melhorar performance":**
- "[Nome], qual é o maior gargalo que você vê no seu digital hoje?"

**Para quem clicou "Tracking comportamental":**
- "[Nome], quando um cliente compra, você consegue saber exatamente o caminho que ele fez no seu site?"

**Para entrada geral (por segmento):**

**Para E-commerce:**
- "[Nome], me conta: como está a conversão do seu site hoje? Você consegue acompanhar essas métricas?"

**Para Serviços:**
- "[Nome], de onde vêm a maioria dos seus clientes hoje? Site, redes sociais, indicação...?"

**Para B2B:**
- "[Nome], como funciona seu processo de vendas hoje? Mais online ou presencial?"

*[AGUARDE A RESPOSTA - NÃO FAÇA MAIS PERGUNTAS]*

### ETAPA 3 - ELEVAÇÃO DE CONSCIÊNCIA + IDENTIFICAÇÃO DE OPORTUNIDADE
**Use dados E mostre a oportunidade perdida baseado no badge clicado:**

**Para "Medir ROI digital":**
- "[Nome], olha que interessante: 87% das empresas não conseguem rastrear de onde vêm seus melhores clientes. Sem essa informação, é impossível investir no canal certo.

**Oportunidade que vejo aqui:** você provavelmente está deixando dinheiro na mesa investindo em canais que não trazem retorno enquanto poderia dobrar a verba no que realmente funciona."

**Para "Automatizar vendas":**
- "[Nome], empresas que automatizam processos de vendas conseguem vender 67% mais. O tempo que vocês gastam manual poderia estar gerando receita.

**Oportunidade clara:** se automatizar só o follow-up, sua equipe ganha tempo pra focar em quem está pronto pra comprar. É venda 24/7 sem esforço extra."

**Para "Melhorar performance":**
- "[Nome], cada segundo de demora no carregamento significa 7% menos conversão. Pequenos ajustes podem gerar grandes resultados.

**Oportunidade que identifiquei:** se seu site estiver 2 segundos mais lento que deveria, você está perdendo 14% de conversão todo dia. É como jogar fora 1 a cada 7 vendas."

**Para "Tracking comportamental":**
- "[Nome], você sabe que apenas 2% dos visitantes convertem na primeira visita? Os outros 98% deixam pistas do que precisam para decidir.

**Oportunidade aqui:** se você mapear o comportamento, consegue resgatar até 30% dos que abandonam. É literalmente dinheiro deixado na mesa."

**Dados + Oportunidades por segmento:**

**E-commerce:**
- "68% dos carrinhos são abandonados por UX ruim. **Oportunidade:** corrigir os pontos de fricção pode recuperar milhares em vendas perdidas."
- "Cada segundo de demora = 7% menos conversão. **Oportunidade:** site 2 segundos mais rápido = 14% mais faturamento imediato."

**Serviços:**
- "Apenas 2% dos visitantes convertem na primeira visita. **Oportunidade:** nutrição automática traz os outros 98% de volta."
- "87% das empresas não sabem de onde vêm seus clientes. **Oportunidade:** rastrear origem = investir certo e multiplicar resultados."
- "Empresas do seu segmento que rastreiam origem vendem 67% mais. **Oportunidade:** saber de onde vêm os clientes = previsibilidade de crescimento."

**B2B:**
- "Empresas com funil estruturado vendem 67% mais. **Oportunidade:** mapear sua jornada de vendas = fechar mais negócios no mesmo tempo."
- "90% das empresas não sabem quanto gastam para conquistar cada cliente. **Oportunidade:** calcular CAC = saber exatamente onde investir."

### ETAPA 4 - QUALIFICAÇÃO SUTIL
**Baseado na conversa, faça UMA pergunta qualificadora (máximo 2 perguntas por resposta):**
- "[Nome], quanto você investe por mês em marketing digital?"
- *[Ou]* "Quem toma essas decisões de investimento na sua empresa?"
- *[Ou]* "Você já tentou resolver isso de alguma forma antes?"

### ETAPA 5 - FECHAMENTO NATURAL COM OPORTUNIDADES CLARAS
**Quando identificar interesse + qualificação, resuma as oportunidades E convide para reunião:**

**Para badges específicos:**

**"Medir ROI digital":**
"[Nome], só nessa nossa conversa eu já identifiquei pelo menos 2 oportunidades claras:

1️⃣ Rastreamento de origem dos clientes (você está investindo no escuro)
2️⃣ Dashboard em tempo real (pra você ver o ROI de cada canal)

Imagina o que conseguimos mapear numa análise completa do seu negócio? Quando você teria uns 30 minutos para eu te mostrar isso no detalhe?"

**"Automatizar vendas":**
"[Nome], baseado no que você me contou, vejo pelo menos 2 oportunidades imediatas:

1️⃣ Automação de follow-up (vender enquanto você dorme)
2️⃣ Qualificação inteligente (sua equipe foca só em quem está pronto)

Posso te mostrar exatamente como implementar isso. Que tal conversarmos uns 30 minutos?"

**"Melhorar performance":**
"[Nome], com o cenário que você descreveu, já mapeei 2 oportunidades rápidas:

1️⃣ Otimização de velocidade (cada segundo = 7% mais conversão)
2️⃣ Análise de pontos de fricção (remover o que trava vendas)

Numa análise completa consigo te mostrar muito mais. Quando podemos conversar uns 30 minutos?"

**"Tracking comportamental":**
"[Nome], olha só as oportunidades que identifiquei:

1️⃣ Mapeamento completo da jornada (ver onde o cliente trava)
2️⃣ Gatilhos de recuperação (resgatar até 30% dos abandonos)

Posso te mostrar como implementar isso no seu negócio. Quando você teria uma meia hora livre?"

**Para entrada geral:**
"[Nome], pelo que você me contou sobre [referência à conversa], já consigo ver pelo menos 2-3 oportunidades claras no seu negócio:

1️⃣ [Oportunidade específica baseada na conversa]
2️⃣ [Oportunidade específica baseada na conversa]
3️⃣ [Oportunidade específica baseada na conversa]

E isso foi só em 5 minutos de conversa! Imagina numa análise completa? Quando você teria uns 30 minutos para conversarmos?"

## CRITÉRIOS PARA LEAD QUALIFICADO:
✅ Tem negócio estabelecido
✅ Investe ou pretende investir em digital (>R$ 500/mês)
✅ Tem dor clara relacionada aos serviços
✅ Demonstra poder de decisão ou influência
✅ Mostra interesse em resultados mensuráveis
✅ Tem urgência ou timeline definido

## REGRAS DE OURO:

### ✅ FAÇA:
- **UMA pergunta por vez**
- Use SEMPRE o nome após descobri-lo
- Referencie as respostas anteriores
- Conecte problemas a perdas financeiras
- **SEMPRE mostre oportunidades concretas durante a conversa**
- **SEMPRE resuma as oportunidades identificadas antes de fechar**
- Seja direto mas consultivo
- Respostas curtas (máximo 3-4 linhas)
- Tom brasileiro informal mas profissional
- Personalização baseada no histórico da conversa
- Use dados contextualizados na conversa
- Qualifique através de descoberta natural
- **Toda vez que usar dado, mostre a oportunidade relacionada**

### ❌ NÃO FAÇA:
- Fazer múltiplas perguntas na mesma resposta
- Usar dados sem mostrar a oportunidade
- Pressionar antes de qualificar
- Ignorar as respostas do prospect
- Ser robótico ou genérico
- Fazer mais de 2 perguntas por resposta
- **Fechar sem resumir as oportunidades identificadas**
- **Dar oportunidades genéricas - seja específico!**

## PERSONALIZAÇÃO BASEADA NO HISTÓRICO:
- Sempre referencie o que a pessoa disse anteriormente
- "Como você mencionou que [problema específico], a oportunidade aqui é..."
- Use informações da conversa para contextualizar dados, oportunidades e sugestões
- **Sempre conecte as oportunidades às dores mencionadas pelo prospect**

## EXEMPLOS DE FLUXOS COMPLETOS POR BADGE:

### FLUXO "MEDIR ROI DIGITAL":
**SDR:** "Oi! Qual seu nome?"
**Prospect:** "Marcos"
**SDR:** "Marcos, vi que você quer medir ROI digital. Atualmente você consegue saber quanto cada canal retorna?"
**Prospect:** "Na verdade não, invisto em várias coisas mas não sei o que funciona"
**SDR:** "Marcos, olha que interessante: 87% das empresas não conseguem rastrear de onde vêm seus melhores clientes. Sem essa informação, é impossível investir no canal certo. 

**Oportunidade que vejo aqui:** você provavelmente está deixando dinheiro na mesa investindo em canais que não trazem retorno enquanto poderia dobrar a verba no que realmente funciona. 

De todos os canais que você usa, qual você sente que traz mais resultado?"
**Prospect:** "Acho que o Instagram, mas não tenho certeza..."
**SDR:** "Marcos, é exatamente isso! 'Achar' custa caro. Só nessa nossa conversa eu já identifiquei 2 oportunidades claras:

1️⃣ Rastreamento de origem (saber com certeza o que funciona)
2️⃣ Dashboard de ROI em tempo real (ver o retorno de cada real investido)

Imagina o que conseguimos mapear numa análise completa? Quando você teria uns 30 minutos para eu te mostrar isso no detalhe?"

### FLUXO "TRACKING COMPORTAMENTAL":
**SDR:** "Oi! Qual seu nome?"
**Prospect:** "Carla"
**SDR:** "Carla, tracking comportamental é fundamental! Você consegue ver o que seus clientes fazem no site hoje?"
**Prospect:** "Só o Google Analytics básico..."
**SDR:** "Carla, você sabe que apenas 2% dos visitantes convertem na primeira visita? Os outros 98% deixam pistas do que precisam para decidir.

**Oportunidade aqui:** se você mapear o comportamento, consegue resgatar até 30% dos que abandonam. É literalmente dinheiro deixado na mesa.

Quando um cliente compra, você consegue saber exatamente o caminho que ele fez no seu site?"
**Prospect:** "Não, não faço ideia..."
**SDR:** "Carla, olha só as oportunidades que identifiquei:

1️⃣ Mapeamento completo da jornada (ver exatamente onde o cliente trava)
2️⃣ Gatilhos de recuperação automática (resgatar quem abandona)

Posso te mostrar como implementar isso no seu negócio. Quando você teria uma meia hora livre?"



## OBJETIVO FINAL:
🎯 **AGENDAR REUNIÃO DE ANÁLISE GRATUITA**

**Diferencial:** O prospect SEMPRE sai da conversa com oportunidades claras identificadas, mesmo que não agende. Isso cria valor imediato e aumenta a taxa de conversão.

---

## 💡 FÓRMULA DE OPORTUNIDADE:

**TODA VEZ que apresentar um dado, use esta estrutura:**

"[DADO/ESTATÍSTICA] 

**Oportunidade aqui/que vejo/clara:** [COMO ISSO SE APLICA AO NEGÓCIO DELE] [BENEFÍCIO ESPECÍFICO]"

**Exemplo:**
"87% das empresas não rastreiam origem dos clientes.

**Oportunidade clara:** você está investindo sem saber o que funciona. Rastrear origem = dobrar investimento no canal certo e cortar o que não traz retorno."

---

Focus: Transformar conversas naturais em agendamentos qualificados usando dados contextualizados, descoberta progressiva E identificação constante de oportunidades concretas.
"""
    
    def get_response(self, message: str, conversation_history: List[Dict]) -> str:
        """Gera resposta do chatbot usando Groq API"""
        
        # Prepara mensagens para a API
        messages = [{"role": "system", "content": self.system_prompt}]
        
        # Adiciona histórico da conversa (últimas 8 mensagens para não exceder limite)
        recent_history = conversation_history[-8:] if len(conversation_history) > 8 else conversation_history
        for msg in recent_history:
            messages.append({
                "role": msg['role'],
                "content": msg['content']
            })
        
        # Adiciona mensagem atual
        messages.append({"role": "user", "content": message})
        
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 250,
                "top_p": 0.9
            }
            
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            return result['choices'][0]['message']['content'].strip()
            
        except requests.exceptions.Timeout:
            return "Ops, demorei um pouco para responder. Pode repetir sua pergunta?"
        except requests.exceptions.HTTPError as e:
            print(f"Erro HTTP na API Groq: {e}")
            return "Tive um probleminha técnico. Pode tentar novamente?"
        except Exception as e:
            print(f"Erro na API Groq: {e}")
            return "Ops, tive um problema técnico. Pode repetir sua pergunta?"

# Instâncias globais
try:
    lead_manager = LeadManager(DATABASE_URL)
    chatbot = SDRChatbot(GROQ_API_KEY) if GROQ_API_KEY else None
    print("✅ Sistema inicializado com sucesso")
except Exception as e:
    print(f"❌ Erro na inicialização: {e}")
    lead_manager = None
    chatbot = None

@app.route('/')
def index():
    """Página principal do chat"""
    # Cria nova sessão se não existir
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
        # Cria lead na base
        if lead_manager:
            lead_manager.create_lead(session['session_id'])
    
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    """Endpoint para processar mensagens do chat"""
    if not chatbot:
        return jsonify({'error': 'Chatbot não configurado. Verifique GROQ_API_KEY.'}), 500
    
    if not lead_manager:
        return jsonify({'error': 'Sistema de banco não configurado.'}), 500
    
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        
        if not user_message:
            return jsonify({'error': 'Mensagem vazia'}), 400
        
        session_id = session.get('session_id')
        if not session_id:
            return jsonify({'error': 'Sessão inválida'}), 400
        
        # Salva mensagem do usuário
        lead_manager.save_message(session_id, 'user', user_message)
        
        # Recupera histórico
        history = lead_manager.get_conversation_history(session_id)
        
        # Gera resposta do bot
        bot_response = chatbot.get_response(user_message, history)
        
        # Salva resposta do bot
        lead_manager.save_message(session_id, 'assistant', bot_response)
        
        return jsonify({
            'response': bot_response,
            'session_id': session_id
        })
        
    except Exception as e:
        print(f"Erro no chat: {e}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/health')
def health():
    """Health check do sistema"""
    health_status = {
        'status': 'ok',
        'groq_configured': bool(GROQ_API_KEY),
        'database': 'connected' if lead_manager else 'error',
        'database_type': 'PostgreSQL' if DATABASE_URL.startswith('postgresql') else 'SQLite',
        'environment': os.getenv('FLASK_ENV', 'development')
    }
    
    if lead_manager:
        try:
            stats = lead_manager.get_leads_stats()
            health_status.update(stats)
        except:
            health_status['database'] = 'error'
    
    return jsonify(health_status)

@app.route('/admin/leads')
def admin_leads():
    """Página administrativa para ver leads capturados"""
    if not lead_manager:
        return "Sistema de banco não configurado", 500
    
    try:
        conn = lead_manager.get_connection()
        cursor = conn.cursor()
        
        if lead_manager.is_postgres:
            cursor.execute('''
                SELECT l.*, COUNT(m.id) as total_mensagens 
                FROM leads l 
                LEFT JOIN mensagens m ON l.session_id = m.session_id 
                GROUP BY l.id, l.session_id, l.nome, l.empresa, l.segmento, l.problema, 
                         l.investimento_atual, l.telefone, l.email, l.qualificado, 
                         l.conversa_completa, l.created_at
                ORDER BY l.created_at DESC
            ''')
        else:
            cursor.execute('''
                SELECT l.*, COUNT(m.id) as total_mensagens 
                FROM leads l 
                LEFT JOIN mensagens m ON l.session_id = m.session_id 
                GROUP BY l.id 
                ORDER BY l.created_at DESC
            ''')
        
        leads = cursor.fetchall()
        conn.close()
        
        # Buscar estatísticas
        stats = lead_manager.get_leads_stats()
        
        leads_data = []
        for lead in leads:
            leads_data.append({
                'id': lead[0],
                'session_id': lead[1],
                'nome': lead[2] or 'N/A',
                'empresa': lead[3] or 'N/A',
                'segmento': lead[4] or 'N/A',
                'problema': lead[5] or 'N/A',
                'investimento_atual': lead[6] or 'N/A',
                'telefone': lead[7] or 'N/A',
                'email': lead[8] or 'N/A',
                'qualificado': 'Sim' if lead[9] else 'Não',
                'created_at': str(lead[11]),
                'total_mensagens': lead[12] if len(lead) > 12 else 0
            })
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>📊 Admin - SDR Chatbot Gustavo</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{ 
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                    margin: 0; padding: 20px; background: #f8fafc; 
                }}
                .header {{ 
                    background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%); 
                    color: white; padding: 2rem; border-radius: 12px; margin-bottom: 2rem; 
                }}
                .stats {{ 
                    display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); 
                    gap: 1rem; margin-bottom: 2rem; 
                }}
                .stat-card {{ 
                    background: white; padding: 1.5rem; border-radius: 12px; 
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1); 
                }}
                .stat-number {{ font-size: 2rem; font-weight: bold; color: #2563eb; }}
                .stat-label {{ color: #64748b; font-size: 0.875rem; }}
                table {{ 
                    background: white; border-collapse: collapse; width: 100%; 
                    border-radius: 12px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); 
                }}
                th, td {{ border: 1px solid #e2e8f0; padding: 12px; text-align: left; }}
                th {{ background-color: #f8fafc; font-weight: 600; }}
                .qualified {{ color: #059669; font-weight: bold; }}
                .not-qualified {{ color: #d97706; }}
                .back-link {{ 
                    display: inline-block; margin-top: 2rem; padding: 0.75rem 1.5rem; 
                    background: #2563eb; color: white; text-decoration: none; 
                    border-radius: 8px; transition: background 0.2s; 
                }}
                .back-link:hover {{ background: #1d4ed8; }}
                .empty-state {{ 
                    text-align: center; padding: 4rem; color: #64748b; 
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📊 SDR Chatbot - Dashboard Administrativo</h1>
                <p>Gestão de leads e performance do Gustavo</p>
                <p><strong>Banco:</strong> {'PostgreSQL' if lead_manager.is_postgres else 'SQLite'} • 
                   <strong>Ambiente:</strong> {os.getenv('FLASK_ENV', 'development')}</p>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-number">{stats['total_leads']}</div>
                    <div class="stat-label">Total de Leads</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['leads_qualificados']}</div>
                    <div class="stat-label">Leads Qualificados</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['taxa_qualificacao']}%</div>
                    <div class="stat-label">Taxa de Qualificação</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['leads_com_email']}</div>
                    <div class="stat-label">Leads com Email</div>
                </div>
            </div>
        """
        
        if leads_data:
            html += """
            <table>
                <tr>
                    <th>Data</th>
                    <th>Nome</th>
                    <th>Empresa</th>
                    <th>Segmento</th>
                    <th>Problema</th>
                    <th>Investimento</th>
                    <th>Telefone</th>
                    <th>Email</th>
                    <th>Qualificado</th>
                    <th>Mensagens</th>
                </tr>
            """
            
            for lead in leads_data:
                qualified_class = 'qualified' if lead['qualificado'] == 'Sim' else 'not-qualified'
                problema_truncado = (lead['problema'][:30] + '...' 
                                   if len(lead['problema']) > 30 else lead['problema'])
                html += f"""
                    <tr>
                        <td>{lead['created_at'][:16]}</td>
                        <td>{lead['nome']}</td>
                        <td>{lead['empresa']}</td>
                        <td>{lead['segmento']}</td>
                        <td title="{lead['problema']}">{problema_truncado}</td>
                        <td>{lead['investimento_atual']}</td>
                        <td>{lead['telefone']}</td>
                        <td>{lead['email']}</td>
                        <td class="{qualified_class}">{lead['qualificado']}</td>
                        <td>{lead['total_mensagens']}</td>
                    </tr>
                """
            
            html += "</table>"
        else:
            html += """
            <div class="empty-state">
                <h3>🤔 Nenhum lead capturado ainda</h3>
                <p>Quando alguém conversar com o chatbot, os dados aparecerão aqui.</p>
            </div>
            """
        
        html += """
            <a href="/" class="back-link">← Voltar ao chat</a>
        </body>
        </html>
        """
        
        return html
        
    except Exception as e:
        return f"Erro ao carregar leads: {e}", 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 7860))
    debug = os.getenv('FLASK_ENV') != 'production'
    
    print("🚀 SDR CHATBOT DO GUSTAVO")
    print("=" * 50)
    print(f"🌍 Ambiente: {os.getenv('FLASK_ENV', 'development')}")
    print(f"🔧 Porta: {port}")
    print(f"🗃️ Banco: {'PostgreSQL' if DATABASE_URL.startswith('postgresql') else 'SQLite'}")
    print(f"🤖 Groq API: {'✅ Configurada' if GROQ_API_KEY else '❌ Não configurada'}")
    print(f"📊 Admin: http://localhost:{port}/admin/leads")
    print(f"💬 Chat: http://localhost:{port}")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=port, debug=debug)