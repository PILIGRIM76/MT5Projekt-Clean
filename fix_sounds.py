"""
Генератор звуковых файлов для Genesis Trading System
Создает простые WAV файлы которые гарантированно работают с QSoundEffect
"""

import os
import struct


def generate_tone(filename, frequency, duration_ms, volume=0.5):
    """
    Генерирует простой тон в формате WAV

    Args:
        filename: Имя файла
        frequency: Частота в Гц
        duration_ms: Длительность в миллисекундах
        volume: Громкость 0.0-1.0
    """
    sample_rate = 44100
    num_samples = int(sample_rate * duration_ms / 1000)

    # Генерируем синусоиду
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        # Применяем envelope для плавного начала/конца
        envelope = 1.0
        if i < 1000:  # Attack 22ms
            envelope = i / 1000.0
        if i > num_samples - 1000:  # Release 22ms
            envelope = (num_samples - i) / 1000.0

        sample = volume * envelope * (32767 * 0.5)  # Уменьшаем громкость

        # Простая синусоида
        import math

        value = int(sample * math.sin(2 * math.pi * frequency * t))
        # Clamp
        value = max(-32768, min(32767, value))
        samples.append(value)

    # Записываем WAV файл
    with open(filename, "wb") as f:
        # WAV header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + len(samples) * 2))  # File size - 8
        f.write(b"WAVE")

        # fmt chunk
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))  # Chunk size
        f.write(struct.pack("<H", 1))  # PCM format
        f.write(struct.pack("<H", 1))  # Mono
        f.write(struct.pack("<I", sample_rate))  # Sample rate
        f.write(struct.pack("<I", sample_rate * 2))  # Byte rate
        f.write(struct.pack("<H", 2))  # Block align
        f.write(struct.pack("<H", 16))  # Bits per sample

        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", len(samples) * 2))  # Data size

        for sample in samples:
            f.write(struct.pack("<h", sample))

    print(f"✅ Создан: {filename} ({frequency}Hz, {duration_ms}ms)")


def main():
    sounds_dir = os.path.dirname(os.path.abspath(__file__))

    print(f"Генерация звуков в: {sounds_dir}\n")

    # Генерируем 5 звуков
    generate_tone(os.path.join(sounds_dir, "alert.wav"), 880, 200)  # Высокий писк (предупреждение)
    generate_tone(os.path.join(sounds_dir, "error.wav"), 440, 400)  # Низкий длинный (ошибка)
    generate_tone(os.path.join(sounds_dir, "system_start.wav"), 1200, 300)  # Мелодичный (старт)
    generate_tone(os.path.join(sounds_dir, "system_stop.wav"), 600, 300)  # Грустный (стоп)
    generate_tone(os.path.join(sounds_dir, "trade_open.wav"), 1000, 150)  # Короткий радостный (сделка)

    print("\n✅ Все звуки созданы!")
    print("\n💡 Теперь нужно изменить код чтобы использовать .wav вместо .mp3")
    print("   Или сконвертировать .wav в .mp3 через ffmpeg:")
    print("   ffmpeg -i alert.wav -codec:a libmp3lame -qscale:a 2 alert.mp3")


if __name__ == "__main__":
    main()
