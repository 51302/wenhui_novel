-- ============================================
-- 文辉小说 (easy-novel) 数据库初始化脚本
-- ============================================

CREATE DATABASE IF NOT EXISTS `easy-novel`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `easy-novel`;

-- 用户表
CREATE TABLE IF NOT EXISTS `users` (
  `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '用户ID',
  `username` VARCHAR(64) NOT NULL UNIQUE COMMENT '用户名',
  `password` VARCHAR(256) NOT NULL COMMENT '密码(bcrypt加密)',
  `jwt_token` VARCHAR(512) DEFAULT NULL COMMENT '当前JWT Token',
  `status` TINYINT DEFAULT 1 COMMENT '状态: 0=禁用, 1=正常',
  `email` VARCHAR(128) DEFAULT NULL COMMENT '邮箱',
  `phone` VARCHAR(20) DEFAULT NULL COMMENT '手机号',
  `vip_level` TINYINT DEFAULT 0 COMMENT 'VIP等级: 0=免费, 1=VIP, 2=SVIP',
  `vip_expire_at` DATETIME DEFAULT NULL COMMENT 'VIP过期时间',
  `free_generate_quota` INT DEFAULT 6 COMMENT '每日AI生成剩余配额',
  `quota_date` DATE DEFAULT NULL COMMENT '配额日期(用于跨天重置)',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  INDEX `idx_username` (`username`),
  INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表';

-- 插入默认超级管理员账号
-- 用户名: superuser1
-- 密码: super123 (bcrypt加密后的hash)
INSERT INTO `users` (`username`, `password`, `vip_level`, `status`, `free_generate_quota`, `quota_date`) VALUES
('superuser1', '$2b$12$fUWTUPXaIP1lmECa/BP1yOgW9KXI9QdT2afC0AOCTqOQOy50BXY7O', 2, 1, 50, CURDATE())
ON DUPLICATE KEY UPDATE `vip_level` = 2, `status` = 1;

-- 小说作品表
CREATE TABLE IF NOT EXISTS `novels` (
  `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '作品自增ID',
  `novel_unique_id` VARCHAR(64) NOT NULL UNIQUE COMMENT '作品唯一ID',
  `author_user_id` INT NOT NULL COMMENT '作者用户ID',
  `author_name` VARCHAR(64) NOT NULL COMMENT '作者用户名/作者别名',
  `title` VARCHAR(256) NOT NULL COMMENT '书名/作品名称',
  `target_reader` VARCHAR(16) NOT NULL COMMENT '作品类型/目标读者: 男频/女频',
  `genre` VARCHAR(64) DEFAULT NULL COMMENT '题材/标签',
  `description` TEXT COMMENT '作品简介',
  `story_background` TEXT COMMENT '故事背景',
  `world_setting` TEXT COMMENT '世界观设定',
  `realm_setting` TEXT COMMENT '境界设定(JSON)',
  `characters` LONGTEXT COMMENT '角色设定(JSON)',
  `cover_image` VARCHAR(512) DEFAULT NULL COMMENT '封面图片',
  `plot_development` TEXT COMMENT '剧情发展路线',
  `sign_type` VARCHAR(16) DEFAULT 'non_exclusive' COMMENT '签约类型: exclusive=独家, non_exclusive=非独家',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `created_by` VARCHAR(64) DEFAULT NULL COMMENT '创建人',
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  INDEX `idx_author_user_id` (`author_user_id`),
  INDEX `idx_target_reader` (`target_reader`),
  INDEX `idx_genre` (`genre`),
  INDEX `idx_title` (`title`),
  INDEX `idx_author_name` (`author_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='小说作品表';

-- 章节表
CREATE TABLE IF NOT EXISTS `chapters` (
  `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '章节自增ID',
  `novel_unique_id` VARCHAR(64) NOT NULL COMMENT '作品唯一ID',
  `user_id` INT NOT NULL COMMENT '用户ID',
  `chapter_unique_id` VARCHAR(64) NOT NULL UNIQUE COMMENT '章节唯一ID',
  `chapter_name` VARCHAR(256) NOT NULL COMMENT '章节名称',
  `chapter_number` INT DEFAULT 0 COMMENT '章节序号(如1,2,3...)',
  `chapter_summary` TEXT DEFAULT NULL COMMENT '本章概要',
  `is_published` TINYINT DEFAULT 0 COMMENT '是否发布: 0=草稿, 1=已发布',
  `word_count` INT DEFAULT 0 COMMENT '章节字数',
  `created_by` VARCHAR(64) DEFAULT NULL COMMENT '创建人',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  INDEX `idx_novel_unique_id` (`novel_unique_id`),
  INDEX `idx_user_id` (`user_id`),
  INDEX `idx_is_published` (`is_published`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='章节表';

-- 作品互动表（作品圈）
CREATE TABLE IF NOT EXISTS `work_interactions` (
  `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增ID',
  `user_id` INT NOT NULL COMMENT '用户ID(被互动者)',
  `novel_unique_id` VARCHAR(64) NOT NULL COMMENT '作品唯一ID',
  `comment_text` TEXT DEFAULT NULL COMMENT '评论内容',
  `is_like` TINYINT DEFAULT 0 COMMENT '是否点赞: 0=否, 1=是',
  `is_follow` TINYINT DEFAULT 0 COMMENT '是否关注: 0=否, 1=是',
  `is_bookmark` TINYINT DEFAULT 0 COMMENT '是否收藏: 0=否, 1=是',
  `interactor_id` INT NOT NULL COMMENT '评论/点赞/关注/收藏者ID',
  `interactor_name` VARCHAR(64) DEFAULT NULL COMMENT '互动者用户名',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  INDEX `idx_novel_unique_id` (`novel_unique_id`),
  INDEX `idx_interactor_id` (`interactor_id`),
  INDEX `idx_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='作品互动表';

-- 书架表
CREATE TABLE IF NOT EXISTS `bookshelf` (
  `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增ID',
  `user_id` INT NOT NULL COMMENT '用户ID',
  `novel_unique_id` VARCHAR(64) NOT NULL COMMENT '作品唯一ID',
  `last_chapter_unique_id` VARCHAR(64) DEFAULT NULL COMMENT '最后阅读章节ID',
  `last_chapter_name` VARCHAR(256) DEFAULT NULL COMMENT '最后阅读章节名称',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '加入时间',
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  INDEX `idx_user_id` (`user_id`),
  INDEX `idx_novel_unique_id` (`novel_unique_id`),
  UNIQUE KEY `uk_user_novel` (`user_id`, `novel_unique_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='书架表';
