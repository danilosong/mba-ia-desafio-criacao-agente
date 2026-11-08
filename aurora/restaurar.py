"""Comando de restauração: uv run python -m aurora.restaurar"""

from aurora import banco

if __name__ == "__main__":
    banco.restaurar()
    print("Reservas e visitantes restaurados ao estado inicial de dados/.")
