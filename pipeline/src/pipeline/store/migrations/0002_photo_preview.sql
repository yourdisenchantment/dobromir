-- Фото для показа (2026-10-25): вместо исходного JPEG - WebP до 1600 px (file) и
-- превью до 800 px для карточки. Превью может совпадать с file (маленькое фото).
-- preview_file NULL - запись старого вида: скачивание фото пересчитает ее из файла.
ALTER TABLE photos ADD COLUMN preview_file TEXT;
ALTER TABLE photos ADD COLUMN preview_width INTEGER;
ALTER TABLE photos ADD COLUMN preview_height INTEGER;
