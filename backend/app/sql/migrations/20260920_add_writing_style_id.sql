-- Existing installations need this additive migration.
ALTER TABLE `novels`
  ADD COLUMN `writing_style_id` VARCHAR(64) DEFAULT NULL
  COMMENT '作品默认写作风格 Skill ID';
