"""
Configuração global do pytest.

Insere src/ na posição 0 de sys.path ANTES de qualquer importação de testes,
garantindo que os pacotes da aplicação (em src/) são sempre encontrados primeiro.
"""
import sys
from pathlib import Path

_src = str(Path(__file__).parent / "src")
if _src in sys.path:
    sys.path.remove(_src)
sys.path.insert(0, _src)

