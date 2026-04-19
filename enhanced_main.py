# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                  المساعد القانوني القطري المُحسّن - MAX Edition                      ║
║               Qatari Legal Assistant - MAX Edition                                  ║
║                                                                                  ║
║  النظام الشامل للاستفسارات القانونية القطرية مع:                                   ║
║  • دعم متعدد اللهجات العربية (الخليجية، المصرية، الشامية، العراقية)                ║
║  • تحليل القصد والفهم اللغوي المتقدم                                              ║
║  • كشف وتحليل الغموض في الأسئلة                                                  ║
║  • تصنيف المجال القانوني بدقة                                                     ║
║  • تنسيق الإجابات القانونية الاحترافية                                            ║
╚══════════════════════════════════════════════════════════════════════════════════════╝

الإصدار: 3.0-MAX
التاريخ: 2024
"""

import os
import sys
import json
import time
import asyncio
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

# FastAPI و Pydantic
from fastapi import FastAPI, HTTPException, Request, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import httpx

# Base de données
import asyncpg

# Configuration
from enhanced_system.config import Settings, get_settings

# ═══════════════════════════════════════════════════════════════════════════════════════
# Import Modules Système
# ═══════════════════════════════════════════════════════════════════════════════════════

try:
    from enhanced_system.query_engine import EnhancedQueryExpansionEngine
    from enhanced_system.context_manager import EnhancedContextManager
    from enhanced_system.intelligence_layer import (
        EnhancedIntelligenceLayer,
        FormattingContext,
        IntentCategory,
        DialectType,
        ResponseStyle,
    )
    from enhanced_system.domain_relevance_engine import (
        EnhancedDomainRelevanceEngine,
        DomainAnalysis,
        LegalDomain,
    )
    from enhanced_system.ultra_linguistic_engine import (
        UltraLinguisticEngine,
        MAX_AVAILABLE,
    )
    from enhanced_system.legal_correction_engine import (
        LegalCorrectionEngine,
        CorrectionReport,
    )
    from enhanced_system.answer_validator import (
        AnswerValidator,
        AnswerValidationReport,
        ValidationStatus,
    )
    print(f"✓ تم تحميل جميع الوحدات المُحسّنة (MAX_AVAILABLE: {MAX_AVAILABLE})")
    CORRECTION_ENGINE_AVAILABLE = True
    VALIDATOR_AVAILABLE = True
except ImportError as e:
    print(f"⚠ تعذر تحميل بعض الوحدات: {e}")
    EnhancedQueryExpansionEngine = None
    EnhancedContextManager = None
    EnhancedIntelligenceLayer = None
    EnhancedDomainRelevanceEngine = None
    UltraLinguisticEngine = None
    MAX_AVAILABLE = False
    CORRECTION_ENGINE_AVAILABLE = False
    VALIDATOR_AVAILABLE = False

# ═══════════════════════════════════════════════════════════════════════════════════════
# Configuration de l'Application
# ═══════════════════════════════════════════════════════════════════════════════════════

# Load .env
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8-sig").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            if _v.strip():
                os.environ[_k.strip()] = _v.strip()

# Paramètres
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# Configuration base de données
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "ragdb"),
    "user": os.getenv("DB_USER", "raguser"),
    "password": os.getenv("DB_PASSWORD", "RAGsecret2024!"),
}

# ═══════════════════════════════════════════════════════════════════════════════════════
# Modèles de Données
# ═══════════════════════════════════════════════════════════════════════════════════════

class QueryRequest(BaseModel):
    """Modèle de requête"""
    query: str = Field(..., min_length=1, max_length=2000, description="Question juridique")
    session_id: Optional[str] = Field(None, description="ID de session")
    model: Optional[str] = Field("ollama", description="Modèle à utiliser")
    max_sources: int = Field(5, ge=1, le=20, description="Nombre maximum de sources")
    include_reasoning: bool = Field(False, description="Inclure le raisonnement interne")
    response_style: Optional[str] = Field(None, description="Style de réponse")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "ما هي عقوبة السرقة في قطر؟",
                "session_id": "user_123",
                "model": "ollama"
            }
        }

class QueryResponse(BaseModel):
    """Modèle de réponse"""
    answer: str
    sources: List[Dict[str, Any]]
    confidence: float
    session_id: str
    dialect: Optional[str] = None
    dialect_confidence: Optional[float] = None
    intent: Optional[str] = None
    domain: Optional[str] = None
    response_time: float
    cached: bool = False
    model_used: str
    quality_info: Optional[Dict[str, Any]] = None  # معلومات الجودة من MAX Edition
    validation_info: Optional[Dict[str, Any]] = None  # معلومات التحقق
    correction_info: Optional[Dict[str, Any]] = None  # معلومات التصحيح

class HealthResponse(BaseModel):
    """Modèle de santé"""
    status: str
    version: str
    database: str
    ollama: str
    claude: Optional[str] = None
    features: List[str]

class DebugSearchResponse(BaseModel):
    """Modèle de recherche debug"""
    query: str
    expanded_queries: List[str]
    dialect: str
    dialect_confidence: float
    intent: str
    domain: str
    chunks_total: int
    chunks_raw: int
    relevant_after_score_filter: int
    final_chunks: int

# ═══════════════════════════════════════════════════════════════════════════════════════
# Configuration du Serveur
# ═══════════════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Cycle de vie de l'application"""
    # Démarrage
    print("=" * 70)
    print("🚀 Démarrage du Assistant Juridique Qatar - MAX Edition")
    print("=" * 70)

    # Initialisation de la base de données
    app.state.db = None
    try:
        app.state.db = await asyncpg.connect(**DB_CONFIG)
        print("✓ Base de données connectée")
    except Exception as e:
        print(f"⚠ Base de données non disponible: {e}")

    # Initialisation des modules
    app.state.query_engine = None
    app.state.context_manager = None
    app.state.intelligence_layer = None
    app.state.domain_engine = None
    app.state.ultra_engine = None
    app.state.correction_engine = None
    app.state.validator = None

    if EnhancedQueryExpansionEngine:
        app.state.query_engine = EnhancedQueryExpansionEngine()
        print("✓ Query Engine (Enhanced) initialisé")

    if EnhancedContextManager:
        app.state.context_manager = EnhancedContextManager()
        print("✓ Context Manager (Enhanced) initialisé")

    if EnhancedIntelligenceLayer:
        app.state.intelligence_layer = EnhancedIntelligenceLayer()
        print("✓ Intelligence Layer (Enhanced) initialisé")

    if EnhancedDomainRelevanceEngine:
        app.state.domain_engine = EnhancedDomainRelevanceEngine()
        print("✓ Domain Relevance Engine (Enhanced) initialisé")

    if UltraLinguisticEngine and MAX_AVAILABLE:
        try:
            app.state.ultra_engine = UltraLinguisticEngine()
            print("✓ UltraLinguisticEngine (MAX) initialisé")
        except:
            pass

    # Initialisation des nouveaux modules MAX Edition
    if CORRECTION_ENGINE_AVAILABLE and LegalCorrectionEngine:
        try:
            app.state.correction_engine = LegalCorrectionEngine()
            print("✓ LegalCorrectionEngine (MAX) initialisé")
        except Exception as e:
            print(f"⚠ تعذر تهيئة LegalCorrectionEngine: {e}")

    if VALIDATOR_AVAILABLE and AnswerValidator:
        try:
            app.state.validator = AnswerValidator()
            print("✓ AnswerValidator (MAX) initialisé")
        except Exception as e:
            print(f"⚠ تعذر تهيئة AnswerValidator: {e}")

    print("=" * 70)
    print("✅ النظام جاهز! (MAX Edition)")
    print("=" * 70)

    yield

    # Arrêt
    if app.state.db:
        await app.state.db.close()
        print("🔴 Base de données déconnectée")

# ═══════════════════════════════════════════════════════════════════════════════════════
# Création de l'Application
# ═══════════════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="المساعد القانوني القطري - MAX Edition",
    description="""نظام متقدم للاستفسارات القانونية القطرية مع:
- دعم اللهجات العربية المختلفة
- تحليل القصد والفهم اللغوي
- تصنيف المجال القانوني
- تنسيق الإجابات القانونية الاحترافية
- تكامل مع Ollama و Claude API""",
    version="3.0-MAX",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════════════════════════
# Fonctions Utilitaires
# ═══════════════════════════════════════════════════════════════════════════════════════

async def get_db(request: Request) -> asyncpg.Connection:
    """Obtenir la connexion DB"""
    if not request.app.state.db:
        raise HTTPException(status_code=503, detail="Base de données non disponible")
    return request.app.state.db

async def search_chunks(
    db: asyncpg.Connection,
    query_embedding: List[float],
    match_threshold: float = 0.5,
    match_count: int = 10
) -> List[Dict]:
    """Rechercher les chunks similaires"""
    try:
        results = await db.fetch("""
            SELECT
                c.id,
                c.content,
                c.law,
                c.article,
                c.chapter,
                c.section,
                c.title,
                c.year,
                1 - (c.embedding <=> $1::vector) as similarity
            FROM chunks c
            WHERE c.is_active = TRUE
            AND c.embedding IS NOT NULL
            AND 1 - (c.embedding <=> $1::vector) > $2
            ORDER BY c.embedding <=> $1::vector
            LIMIT $3
        """, query_embedding, match_threshold, match_count)

        return [dict(r) for r in results]
    except Exception as e:
        print(f"⚠ Erreur de recherche: {e}")
        return []

async def check_ollama() -> bool:
    """Vérifier Ollama"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_HOST}/api/tags")
            return resp.status_code == 200
    except:
        return False

async def get_embedding(text: str) -> Optional[List[float]]:
    """Obtenir l'embedding d'un texte"""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{OLLAMA_HOST}/api/embeddings",
                json={"model": OLLAMA_EMBED_MODEL, "prompt": text}
            )
            if resp.status_code == 200:
                return resp.json().get("embedding")
    except Exception as e:
        print(f"⚠ Erreur embedding: {e}")
    return None

async def generate_response(
    prompt: str,
    model: str = OLLAMA_MODEL,
    max_tokens: int = 1000
) -> Optional[str]:
    """Générer une réponse"""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{OLLAMA_HOST}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"num_predict": max_tokens, "temperature": 0.3}
                }
            )
            if resp.status_code == 200:
                return resp.json().get("message", {}).get("content", "")
    except Exception as e:
        print(f"⚠ Erreur génération: {e}")
    return None

def detect_dialect(text: str) -> Dict[str, Any]:
    """Détecter la dialecte"""
    gulf_words = ["هلا", "والله", "بن", "اب", "يا", "ترا", "وش", "ليش", "هللة"]
    egyptian_words = ["إيه", "اللي", "مش", "عشان", "إزاي", "أولاد", "خبط", "هعمل"]
    levantine_words = ["هلق", "لازم", "كتير", "هيك", "شو", "كيف", "بدي", "عم"]
    iraqi_words = ["هسة", "لا", "اكو", "شنو", "شلون", "المطر", "گلبي", "روحي"]

    text_lower = text.lower()

    scores = {
        "خليجية": sum(1 for w in gulf_words if w in text_lower),
        "مصرية": sum(1 for w in egyptian_words if w in text_lower),
        "شامية": sum(1 for w in levantine_words if w in text_lower),
        "عراقية": sum(1 for w in iraqi_words if w in text_lower),
    }

    max_score = max(scores.values()) if scores else 0
    dialect = max(scores, key=scores.get) if max_score > 0 else "فصحى"
    confidence = min(max_score / 3, 1.0) if max_score > 0 else 0.0

    return {
        "dialect": dialect,
        "confidence": confidence,
        "scores": scores
    }

# ═══════════════════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════════════════

@app.get("/", tags=["Info"])
async def root():
    """Point d'entrée"""
    return {
        "name": "المساعد القانوني القطري - MAX Edition",
        "version": "3.0-MAX",
        "status": "operational"
    }

@app.get("/health", response_model=HealthResponse, tags=["Système"])
async def health_check(request: Request):
    """Vérifier l'état du système"""
    db_status = "✓" if request.app.state.db else "✗"
    ollama_status = "✓" if await check_ollama() else "✗"
    claude_status = "✓" if os.getenv("ANTHROPIC_API_KEY") else "✗ غير مفعّل"

    features = ["enhanced_query_engine"]
    if request.app.state.context_manager:
        features.append("enhanced_context_manager")
    if request.app.state.intelligence_layer:
        features.append("enhanced_intelligence_layer")
    if request.app.state.domain_engine:
        features.append("enhanced_domain_relevance")
    if request.app.state.ultra_engine:
        features.append("ultra_linguistic_engine")
    if request.app.state.correction_engine:
        features.append("legal_correction_engine")
    if request.app.state.validator:
        features.append("answer_validator")

    return HealthResponse(
        status="ok" if request.app.state.db else "degraded",
        version="3.0-MAX",
        database=db_status,
        ollama=ollama_status,
        claude=claude_status,
        features=features
    )

@app.post("/api/v1/query/", response_model=QueryResponse, tags=["API"])
async def query(
    request_data: QueryRequest,
    request: Request,
    background_tasks: BackgroundTasks
):
    """
   포인트: Endpoint principal pour les requêtes juridiques

    - البحث في مصادر القانون القطري
    - تحليل السؤال واستخراج القصد
    - توليد إجابة قانونية دقيقة
    """
    start_time = time.time()

    # ID de session
    session_id = request_data.session_id or hashlib.md5(
        str(datetime.now()).encode()
    ).hexdigest()[:8]

    try:
        # Obtenir les modules
        db = await get_db(request)
        query_engine = request.app.state.query_engine
        context_manager = request.app.state.context_manager
        intelligence_layer = request.app.state.intelligence_layer
        domain_engine = request.app.state.domain_engine
        correction_engine = request.app.state.correction_engine
        validator = request.app.state.validator

        # 1. Analyse du query
        query_analysis = {}
        if query_engine:
            query_analysis = await query_engine.analyze(
                request_data.query,
                use_ultra_engine=bool(request.app.state.ultra_engine)
            )

        # 2. Détection de dialecte
        dialect_info = detect_dialect(request_data.query)
        dialect = dialect_info["dialect"]
        dialect_confidence = dialect_info["confidence"]

        # 3. Embedding
        query_embedding = await get_embedding(request_data.query)
        if not query_embedding:
            raise HTTPException(status_code=500, detail="Échec de l'embedding")

        # 4. Recherche vectorielle
        chunks = await search_chunks(
            db,
            query_embedding,
            match_threshold=0.4,
            match_count=request_data.max_sources + 5
        )

        # 5. Classification du domaine
        domain_analysis = None
        if domain_engine:
            domain_analysis = domain_engine.classify_domain(
                request_data.query,
                sources=chunks
            )

        # 6. Ranking des chunks
        if domain_engine and chunks:
            chunks = domain_engine.rank_chunks(
                chunks,
                request_data.query,
                domain_analysis
            )

        # Limiter aux meilleures sources
        sources = []
        for chunk in chunks[:request_data.max_sources]:
            sources.append({
                "title": chunk.get("title", ""),
                "content": chunk.get("content", "")[:500],
                "law": chunk.get("law", ""),
                "article": chunk.get("article", ""),
                "similarity": chunk.get("similarity", chunk.get("relevance_final", 0))
            })

        # 7. Construire le contexte
        context_prefix = ""
        if context_manager:
            context_prefix = context_manager.build_context_prefix(
                session_id,
                include_linguistic=True
            )
            # Ajouter le message
            context_manager.add_message(
                session_id,
                "user",
                request_data.query,
                query_analysis=query_analysis,
                sources=sources
            )

        # 8. Construire le prompt
        sources_text = "\n\n".join([
            f"[المصدر {i+1}] {s['title']}\n{s['content']}\n(قانون: {s['law']}, مادة: {s['article']})"
            for i, s in enumerate(sources)
        ]) if sources else ""

        dialect_greeting = {
            "خليجية": "هلا والله",
            "مصرية": "أهلاً",
            "شامية": "أهلاً",
            "عراقية": "أهلاً بيك",
            "فصحى": "السلام عليكم"
        }.get(dialect, "السلام عليكم")

        prompt = f"""أنت مساعد قانوني قطري متخصص. أجب بشكل دقيق ومختصر.

{context_prefix}

{dialect_greeting}، سؤال المستخدم: {request_data.query}

المصادر القانونية المتاحة:
{sources_text}

{'_' * 60}

بناءً على المصادر أعلاه، قدم إجابة قانونية دقيقة تتضمن:
1. الإجابة المباشرة على السؤال
2. الأساس القانوني (القانون والمادة)
3. توضيح مختصر إذا لزم الأمر

{'أجب بأسلوب قانوني رسمي.' if request_data.response_style == 'formal' else 'أجب بشكل واضح ومفهوم.'}
"""

        # 9. Générer la réponse
        answer = await generate_response(prompt)

        if not answer:
            answer = "عذراً، لم أتمكن من توليد إجابة. يرجى المحاولة مرة أخرى."

        # 10. تصحيح وتحقق من الإجابة (MAX Edition)
        validation_info = None
        if validator and sources:
            try:
                validation_report = validator.validate(
                    answer=answer,
                    query=request_data.query,
                    sources=sources
                )
                validation_info = {
                    "score": validation_report.overall_score,
                    "status": validation_report.overall_status.value,
                    "passed_checks": validation_report.passed_checks,
                    "total_checks": validation_report.total_checks,
                    "recommendations": validation_report.recommendations[:3] if validation_report.recommendations else []
                }

                # إضافة ملاحظة جودة الإجابة
                if validation_report.overall_score < 0.7:
                    quality_note = f"\n\n---\n⚠️ **ملاحظة جودة:** درجة الجودة {validation_report.overall_score:.0%} - يُنصح بمراجعة التوصيات."
                    answer += quality_note
            except Exception as e:
                print(f"⚠ خطأ في التحقق: {e}")

        # تصحيح الإجابة القانونية
        corrected_answer = answer
        correction_info = None
        if correction_engine and sources:
            try:
                corrected_answer, correction_report = correction_engine.correct(
                    response=answer,
                    query=request_data.query,
                    sources=sources
                )

                # تحديث الإجابة إذا كانت هناك تصحيحات مهمة
                if correction_report.overall_quality_score >= 0.8:
                    answer = corrected_answer

                correction_info = {
                    "quality_score": correction_report.overall_quality_score,
                    "total_issues": correction_report.total_issues,
                    "critical_count": correction_report.critical_count,
                    "recommendations": correction_report.recommendations[:3] if correction_report.recommendations else []
                }
            except Exception as e:
                print(f"⚠ خطأ في التصحيح: {e}")

        # 10. Ajouter au contexte
        if context_manager:
            context_manager.add_message(
                session_id,
                "assistant",
                answer,
                sources=sources
            )

        # 11. Formater la réponse (si intelligence_layer disponible)
        if intelligence_layer and sources:
            formatting_context = FormattingContext(
                dialect=DialectType(dialect) if dialect != "فصحى" else DialectType.MODERN_STANDARD,
                dialect_confidence=dialect_confidence,
                intent=IntentCategory.GENERAL,
                response_style=ResponseStyle.FORMAL_LEGAL,
                domain=domain_analysis.primary_domain.value if domain_analysis else "قانوني عام",
                sources_count=len(sources),
                confidence=sum(s.get("similarity", 0) for s in sources) / len(sources) if sources else 0.5
            )

            answer = intelligence_layer.format_response(
                answer,
                sources,
                formatting_context,
                query_analysis={"query": request_data.query, **query_analysis}
            )

        # 12. Calculer la confiance
        confidence = 0.0
        if sources:
            confidence = sum(s.get("similarity", 0) for s in sources) / len(sources)
            confidence = min(confidence * 100, 99.9)

        elapsed = time.time() - start_time

        # تجميع معلومات الجودة
        quality_info = None
        if validation_info or correction_info:
            quality_info = {
                "validation": validation_info,
                "correction": correction_info
            }

        return QueryResponse(
            answer=answer,
            sources=sources,
            confidence=round(confidence, 1),
            session_id=session_id,
            dialect=dialect,
            dialect_confidence=round(dialect_confidence, 2),
            intent=query_analysis.get("intent", "غير محدد"),
            domain=domain_analysis.primary_domain.value if domain_analysis else "غير محدد",
            response_time=round(elapsed, 2),
            model_used=request_data.model,
            quality_info=quality_info,
            validation_info=validation_info,
            correction_info=correction_info
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"⚠ Erreur query: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/debug_search", response_model=DebugSearchResponse, tags=["Debug"])
async def debug_search(
    q: str,
    request: Request
):
    """Endpoint de debug pour la recherche"""
    try:
        db = await get_db(request)

        # Analyse du query
        dialect_info = detect_dialect(q)

        query_analysis = {}
        if request.app.state.query_engine:
            query_analysis = await request.app.state.query_engine.analyze(q)

        # Domain
        domain = "غير محدد"
        if request.app.state.domain_engine:
            domain_analysis = request.app.state.domain_engine.classify_domain(q)
            domain = domain_analysis.primary_domain.value

        # Embedding et recherche
        query_embedding = await get_embedding(q)

        if not query_embedding:
            return DebugSearchResponse(
                query=q,
                expanded_queries=[q],
                dialect=dialect_info["dialect"],
                dialect_confidence=dialect_info["confidence"],
                intent=query_analysis.get("intent", "غير محدد"),
                domain=domain,
                chunks_total=0,
                chunks_raw=0,
                relevant_after_score_filter=0,
                final_chunks=0
            )

        chunks = await search_chunks(
            db, query_embedding, match_threshold=0.0, match_count=20
        )

        chunks_raw = len(chunks)
        relevant_after_score_filter = len([c for c in chunks if c.get("similarity", 0) > 0.5])

        return DebugSearchResponse(
            query=q,
            expanded_queries=query_analysis.get("expanded_queries", [q]),
            dialect=dialect_info["dialect"],
            dialect_confidence=dialect_info["confidence"],
            intent=query_analysis.get("intent", "غير محدد"),
            domain=domain,
            chunks_total=chunks_raw,
            chunks_raw=chunks_raw,
            relevant_after_score_filter=relevant_after_score_filter,
            final_chunks=min(relevant_after_score_filter, 10)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/session/{session_id}", tags=["Session"])
async def get_session_info(session_id: str, request: Request):
    """Obtenir les informations de session"""
    context_manager = request.app.state.context_manager

    if not context_manager:
        return {"error": "Context manager not available"}

    session = context_manager.get_session_data(session_id)

    if not session:
        return {"error": "Session not found"}

    return {
        "session_id": session_id,
        "messages_count": len(session.messages),
        "linguistic_context": session.linguistic_context.__dict__ if hasattr(session, 'linguistic_context') else {},
        "last_updated": session.last_updated.isoformat() if hasattr(session, 'last_updated') else None
    }

@app.delete("/api/v1/session/{session_id}", tags=["Session"])
async def clear_session(session_id: str, request: Request):
    """Effacer une session"""
    context_manager = request.app.state.context_manager

    if not context_manager:
        return {"success": False, "message": "Context manager not available"}

    success = context_manager.clear_session(session_id)

    return {"success": success, "message": "Session effacée" if success else "Session non trouvée"}

@app.get("/api/v1/domains", tags=["Info"])
async def list_domains(request: Request):
    """Liste des domaines juridiques disponibles"""
    from enhanced_system.domain_relevance_engine import LegalDomain

    domains = []
    for domain in LegalDomain:
        domains.append({
            "value": domain.value,
            "name": domain.name
        })

    return {"domains": domains}

@app.get("/api/v1/laws", tags=["Info"])
async def list_qatari_laws(request: Request):
    """Liste des lois qataries"""
    from enhanced_system.domain_relevance_engine import QATARI_LAWS_MAP

    laws = []
    for law_name, law_info in QATARI_LAWS_MAP.items():
        laws.append({
            "name": law_name,
            "number": law_info.get("الرقم", ""),
            "domain": law_info.get("المجال", {}).value if hasattr(law_info.get("المجال", {}), 'value') else str(law_info.get("المجال", ""))
        })

    return {"laws": laws}

# ═══════════════════════════════════════════════════════════════════════════════════════
# Point d'Entrée
# ═══════════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                  المساعد القانوني القطري - MAX Edition                          ║
║                                                                              ║
║  Serveur API: http://localhost:8000                                         ║
║  Documentation: http://localhost:8000/docs                                   ║
║  Health: http://localhost:8000/health                                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)

    uvicorn.run(
        "enhanced_main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
