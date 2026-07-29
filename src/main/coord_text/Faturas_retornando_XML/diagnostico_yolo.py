"""
Script de diagnóstico para debugar problemas de detecção YOLO
Use este script quando o modelo "fino" não estiver sendo detectado corretamente
"""

from pathlib import Path
from ultralytics import YOLO
import pandas as pd
import io
from PIL import Image
import fitz

# Configurações (mesmo do yolo_pdf_xml.py)
MODEL_PATH = r'C:/ocr_conta_energia/src/runs/detect/yolov8_notas17/weights/best.pt'
PDF_FOLDER = Path(r'C:/ocr_conta_energia/src/main/api/faturas/')
OUT_DIR = Path(r'C:/ocr_conta_energia/src/runs/runs')
CACHE_DETECCOES = OUT_DIR / 'cache_deteccoes.csv'
DPI = 200

print("=" * 60)
print("DIAGNÓSTICO YOLO - DETECÇÃO DE MODELOS")
print("=" * 60)

# 1. Validar modelo
print("\n1️⃣  VALIDAÇÃO DO MODELO:")
try:
    model = YOLO(MODEL_PATH)
    print(f"   ✅ Modelo carregado: {MODEL_PATH}")
    print(f"   📊 Modelo names: {model.names}")
    print(f"   🔢 Número de classes: {len(model.names) if model.names else 0}")
except Exception as e:
    print(f"   ❌ Erro ao carregar modelo: {e}")
    exit(1)

# 2. Listar PDFs
print("\n2️⃣  PDFs DISPONÍVEIS:")
pdf_files = list(PDF_FOLDER.glob('*.pdf'))
print(f"   📄 Encontrados: {len(pdf_files)} PDFs")
for pdf in pdf_files[:5]:  # Mostrar primeiros 5
    print(f"      - {pdf.name}")
if len(pdf_files) > 5:
    print(f"      ... e {len(pdf_files) - 5} mais")

# 3. Testar detecção em 1 PDF
print("\n3️⃣  TESTE DE DETECÇÃO (primeiro PDF):")
if pdf_files:
    pdf_path = pdf_files[0]
    print(f"   Testando: {pdf_path.name}")
    
    try:
        # Extrair primeira página
        with fitz.open(pdf_path) as doc:
            page = doc.load_page(0)
            zoom_matrix = fitz.Matrix(DPI / 72, DPI / 72)
            pix = page.get_pixmap(matrix=zoom_matrix)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        print(f"      ✅ PDF convertido para imagem ({img.size[0]}x{img.size[1]})")
        
        # Fazer predição
        results = model.predict(source=img, conf=0.1, imgsz=640, save=False, verbose=False)
        r = results[0]
        boxes = getattr(r, 'boxes', None)
        
        if not boxes or len(boxes) == 0:
            print(f"      ⚠️  Nenhuma detecção encontrada")
        else:
            print(f"      ✅ Detecções encontradas: {len(boxes)}")
            
            cls_ids = boxes.cls.cpu().numpy().astype(int)
            confidences = boxes.conf.cpu().numpy()
            
            print(f"\n      Detalhes das detecções:")
            for idx, (cls_id, conf) in enumerate(zip(cls_ids, confidences)):
                class_name = model.names[int(cls_id)] if int(cls_id) < len(model.names) else str(cls_id)
                print(f"         [{idx+1}] Classe: {class_name} (ID: {cls_id}) | Confiança: {conf:.3f}")
    
    except Exception as e:
        print(f"      ❌ Erro no teste: {e}")

# 4. Verificar cache
print("\n4️⃣  CACHE DE DETECÇÕES:")
if CACHE_DETECCOES.exists():
    try:
        cache_df = pd.read_csv(CACHE_DETECCOES, header=None, names=['arquivo', 'tipo'])
        print(f"   ✅ Cache encontrado com {len(cache_df)} registros")
        print(f"\n      Distribuição:")
        print(cache_df['tipo'].value_counts().to_string())
        print(f"\n      Primeiros registros:")
        print(cache_df.head(10).to_string(index=False))
    except Exception as e:
        print(f"   ❌ Erro ao ler cache: {e}")
else:
    print(f"   ℹ️  Cache não existe ainda: {CACHE_DETECCOES}")

# 5. Opções de ação
print("\n" + "=" * 60)
print("AÇÕES RECOMENDADAS:")
print("=" * 60)
print("""
1. Se nenhuma detecção foi encontrada:
   → Aumentar confiança mínima em model.predict()
   → Verificar se os nomes das classes estão corretos
   → Tentar com conf=0.05 ou conf=0.01

2. Se "fino" não está sendo detectado:
   → Verificar se o nome da classe é exatamente "fino" (case-sensitive)
   → Procurar variações: "fino", "modelo_fino", "fine", etc.

3. Para limpar o cache e forçar redetecção:
   → Execute: python diagnostico_yolo.py --limpar-cache

4. Para ver todos os PDFs e suas detecções:
   → Execute: python diagnostico_yolo.py --listar-todas

5. Se o problema persistir:
   → Habilite o debug em yolo_pdf_xml.py descomentando:
     diagnosticar_classes_yolo()
""")

# Argumentos de linha de comando
import sys
if len(sys.argv) > 1:
    if sys.argv[1] == '--limpar-cache':
        if CACHE_DETECCOES.exists():
            CACHE_DETECCOES.unlink()
            print(f"\n✅ Cache removido: {CACHE_DETECCOES}")
        else:
            print(f"\n❌ Cache não encontrado")
    
    elif sys.argv[1] == '--listar-todas':
        print(f"\n{'Arquivo':<40} {'Tipo':<15}")
        print("-" * 55)
        if CACHE_DETECCOES.exists():
            try:
                cache_df = pd.read_csv(CACHE_DETECCOES, header=None, names=['arquivo', 'tipo'])
                for _, row in cache_df.iterrows():
                    print(f"{row['arquivo']:<40} {row['tipo']:<15}")
            except Exception as e:
                print(f"Erro: {e}")
        else:
            print("Cache não existe ainda")

print("\n" + "=" * 60)
