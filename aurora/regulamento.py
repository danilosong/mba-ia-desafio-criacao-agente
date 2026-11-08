"""Acesso ao regulamento, sempre um capítulo por vez."""

import re

from aurora.config import DADOS

ASSUNTOS = {
    "Disposições gerais": "disposicoes-gerais",
    "Direitos e deveres dos moradores": "direitos-e-deveres",
    "Silêncio e boa convivência": "silencio-e-convivencia",
    "Piscina": "piscina",
    "Academia, brinquedoteca e playground": "academia-brinquedoteca-playground",
    "Salão de festas, churrasqueira e quadra": "salao-churrasqueira-quadra",
    "Portaria e segurança": "portaria-e-seguranca",
    "Animais de estimação": "animais",
    "Mudanças": "mudancas",
    "Obras e reformas": "obras-e-reformas",
    "Garagem e veículos": "garagem-e-veiculos",
    "Coleta de lixo e reciclagem": "lixo-e-reciclagem",
    "Infrações e penalidades": "infracoes-e-penalidades",
    "Disposições finais": "disposicoes-finais",
}


def _carregar_capitulos() -> dict[str, str]:
    texto = (DADOS / "regulamento.md").read_text(encoding="utf-8")
    blocos = re.split(r"^(?=## Capítulo )", texto, flags=re.MULTILINE)[1:]
    capitulos = {}
    for bloco in blocos:
        titulo = bloco.splitlines()[0].split(":", 1)[1].strip()
        capitulos[ASSUNTOS[titulo]] = bloco.strip()
    return capitulos


CAPITULOS = _carregar_capitulos()
