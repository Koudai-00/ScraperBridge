import React, { useState, useEffect } from 'react';
import {
  StyleSheet,
  View,
  Text,
  Modal,
  TouchableOpacity,
  ScrollView,
  TextInput,
  ActivityIndicator,
  Image,
  Pressable,
  Alert,
  Platform
} from 'react-native';
import { X, Youtube, Globe, SquareCheck as CheckSquare, Square } from 'lucide-react-native';
import Button from './Button';
import FolderPicker from './FolderPicker';
import { useStore } from '@/store';
import { Folder } from '@/types';

interface BulkSaveModalProps {
  visible: boolean;
  onClose: () => void;
}

type TabType = 'youtube' | 'other';

interface FetchedVideo {
  url: string;
  video_title: string;
  thumbnail_url: string;
  video_author_name: string;
  video_platform: string;
  isChecked: boolean;
}



export default function BulkSaveModal({ visible, onClose }: BulkSaveModalProps) {
  const { folders, addVideo } = useStore();
  
  // コンテナの表示状態管理
  const [showInputContainer, setShowInputContainer] = useState(true);
  const [showConfirmContainer, setShowConfirmContainer] = useState(false);

  // フォルダの初期化とデフォルト選択
  useEffect(() => {
    if (folders.length > 0 && !selectedFolderId) {
      setSelectedFolderId(folders[0].id);
    }
  }, [folders]);
  
  // 入力エリアの状態
  const [activeTab, setActiveTab] = useState<TabType>('youtube');
  const [playlistUrl, setPlaylistUrl] = useState('');
  const [multipleUrls, setMultipleUrls] = useState('');
  const [selectedFolderId, setSelectedFolderId] = useState(folders[0]?.id || '');
  const [isProcessing, setIsProcessing] = useState(false);
  
  // 取得動画リストの状態
  const [fetchedVideoList, setFetchedVideoList] = useState<FetchedVideo[]>([]);
  const [selectAll, setSelectAll] = useState(false);
  


  // YouTube再生リストから動画URLを取得
  const getVideosFromPlaylist = async (url: string): Promise<string[]> => {
    const maxRetries = 3;
    const timeout = 10000; // 10秒

    console.log(`[DEBUG] getVideosFromPlaylist: Processing playlist URL: ${url}`);

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        console.log(`[DEBUG] getVideosFromPlaylist: Attempt ${attempt}/${maxRetries}`);
        
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        const requestBody = { url };
        console.log(`[DEBUG] getVideosFromPlaylist: Request body:`, JSON.stringify(requestBody));

        const response = await fetch('https://d9431e70-f6fe-4eb6-9a36-21f141639f26-00-3ks681ngz8cyf.sisko.replit.dev/api/get-videos-from-playlist', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestBody),
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        console.log(`[DEBUG] getVideosFromPlaylist: Response status: ${response.status}`);

        if (!response.ok) {
          const errorText = await response.text();
          console.error(`[DEBUG] getVideosFromPlaylist: Error response body:`, errorText);
          throw new Error(`HTTP ${response.status}: ${response.statusText} - ${errorText}`);
        }

        const data = await response.json();
        console.log(`[DEBUG] getVideosFromPlaylist: Success on attempt ${attempt}, data:`, data);
        
        const videos = data.videos || [];
        console.log(`[DEBUG] getVideosFromPlaylist: Extracted ${videos.length} video URLs:`, videos.map((v: any) => v.videoUrl || v));
        
        // サーバーから返される形式に応じてURLを抽出
        const videoUrls = videos.map((video: any) => {
          if (typeof video === 'string') {
            return video;
          } else if (video.videoUrl) {
            return video.videoUrl;
          } else {
            console.warn(`[DEBUG] getVideosFromPlaylist: Unknown video format:`, video);
            return null;
          }
        }).filter(Boolean);
        
        console.log(`[DEBUG] getVideosFromPlaylist: Final video URLs:`, videoUrls);
        return videoUrls;
      } catch (error) {
        console.error(`[DEBUG] getVideosFromPlaylist: Attempt ${attempt} failed:`, error);
        
        if (attempt === maxRetries) {
          console.error('[DEBUG] getVideosFromPlaylist: All attempts failed');
          return [];
        }
        
        // リトライ前に少し待機
        await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
      }
    }
    
    return [];
  };

  // YouTube再生リストの処理
  const processPlaylistUrl = async () => {
    console.log('[DEBUG] processPlaylistUrl: Starting playlist processing');
    
    if (!playlistUrl.trim()) {
      if (Platform.OS === 'web') {
        window.alert('エラー: 再生リストURLを入力してください');
      } else {
        Alert.alert('エラー', '再生リストURLを入力してください');
      }
      return;
    }

    setIsProcessing(true);
    console.log('[DEBUG] processPlaylistUrl: Set isProcessing to true');

    try {
      // 再生リストから動画URLを取得
      const videoUrls = await getVideosFromPlaylist(playlistUrl);
      console.log('[DEBUG] processPlaylistUrl: Got video URLs:', videoUrls.length);
      
      if (videoUrls.length === 0) {
        if (Platform.OS === 'web') {
          window.alert('エラー: 再生リストから動画を取得できませんでした。\n\n考えられる原因：\n• URLが正しくない\n• 再生リストが非公開\n• ネットワーク接続の問題\n• サーバーの一時的な問題');
        } else {
          Alert.alert(
            'エラー', 
            '再生リストから動画を取得できませんでした。\n\n考えられる原因：\n• URLが正しくない\n• 再生リストが非公開\n• ネットワーク接続の問題\n• サーバーの一時的な問題'
          );
        }
        return;
      }

      const fetchedVideos: FetchedVideo[] = [];
      let successCount = 0;
      let failCount = 0;

      // 各動画のメタデータを取得
      for (const url of videoUrls) {
        // YouTube動画の場合はSupabase Edge Function経由でoEmbedを使用
        const metadata = await getVideoMetadataFromSupabase(url);
        if (metadata) {
          fetchedVideos.push(metadata);
          successCount++;
        } else {
          failCount++;
        }
      }

      console.log('[DEBUG] processPlaylistUrl: Fetched videos:', fetchedVideos.length);
      
      if (fetchedVideos.length === 0) {
        if (Platform.OS === 'web') {
          window.alert(`エラー: 動画の詳細情報を取得できませんでした。\n\n取得試行: ${videoUrls.length}件\n成功: ${successCount}件\n失敗: ${failCount}件\n\nネットワーク接続を確認してから再試行してください。`);
        } else {
          Alert.alert(
            'エラー',
            `動画の詳細情報を取得できませんでした。\n\n取得試行: ${videoUrls.length}件\n成功: ${successCount}件\n失敗: ${failCount}件\n\nネットワーク接続を確認してから再試行してください。`
          );
        }
        return;
      }

      setFetchedVideoList(fetchedVideos);
      setShowInputContainer(false);
      setShowConfirmContainer(true);
      
      // 一部失敗した場合の通知
      if (failCount > 0) {
        if (Platform.OS === 'web') {
          window.alert(`${successCount}件の動画を取得しました。\n${failCount}件の動画は取得できませんでした。`);
        } else {
          Alert.alert('完了', `${successCount}件の動画を取得しました。\n${failCount}件の動画は取得できませんでした。`);
        }
      }
    } catch (error) {
      console.error('[DEBUG] processPlaylistUrl: Error:', error);
      if (Platform.OS === 'web') {
        window.alert('エラー: 再生リストの処理中にエラーが発生しました。\n\nネットワーク接続を確認してから再試行してください。');
      } else {
        Alert.alert('エラー', '再生リストの処理中にエラーが発生しました。\n\nネットワーク接続を確認してから再試行してください。');
      }
    } finally {
      setIsProcessing(false);
      console.log('[DEBUG] processPlaylistUrl: Set isProcessing to false');
    }
  };

  // Instagram用：Replitサーバー経由でメタデータを取得
  const getInstagramMetadata = async (url: string): Promise<FetchedVideo | null> => {
    const maxRetries = 3;
    const timeout = 8000; // 8秒

    console.log(`[DEBUG] getInstagramMetadata: Processing URL: ${url}`);

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        console.log(`[DEBUG] getInstagramMetadata: Attempt ${attempt}/${maxRetries} for URL: ${url}`);
        
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        const requestBody = { url };
        console.log(`[DEBUG] getInstagramMetadata: Request body:`, JSON.stringify(requestBody));

        const response = await fetch('https://d9431e70-f6fe-4eb6-9a36-21f141639f26-00-3ks681ngz8cyf.sisko.replit.dev/api/get-metadata', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestBody),
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        console.log(`[DEBUG] getInstagramMetadata: Response status: ${response.status}`);

        if (!response.ok) {
          const errorText = await response.text();
          console.error(`[DEBUG] getInstagramMetadata: Error response body:`, errorText);
          throw new Error(`HTTP ${response.status}: ${response.statusText} - ${errorText}`);
        }

        const metadata = await response.json();
        console.log(`[DEBUG] getInstagramMetadata: Success on attempt ${attempt}, metadata:`, metadata);
        return {
          url,
          video_title: metadata.title || '',
          thumbnail_url: metadata.thumbnailUrl || '',
          video_author_name: metadata.authorName || '',
          video_platform: metadata.platform || '',
          isChecked: false,
        };
      } catch (error) {
        console.error(`[DEBUG] getInstagramMetadata: Attempt ${attempt} failed for URL ${url}:`, error);
        
        if (attempt === maxRetries) {
          console.error(`[DEBUG] getInstagramMetadata: All attempts failed for URL: ${url}`);
          return null;
        }
        
        // リトライ前に少し待機
        await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
      }
    }
    
    return null;
  };

  // YouTube/TikTok用：Supabase Edge Function経由でoEmbedを使用
  const getVideoMetadataFromSupabase = async (url: string): Promise<FetchedVideo | null> => {
    const maxRetries = 3;
    const timeout = 8000; // 8秒

    console.log(`[DEBUG] getVideoMetadataFromSupabase: Processing URL: ${url}`);

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        console.log(`[DEBUG] getVideoMetadataFromSupabase: Attempt ${attempt}/${maxRetries} for URL: ${url}`);
        
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        const supabaseUrl = process.env.EXPO_PUBLIC_SUPABASE_URL;
        const supabaseKey = process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY;
        
        if (!supabaseUrl || !supabaseKey) {
          console.error('[DEBUG] getVideoMetadataFromSupabase: Supabase environment variables not configured');
          return null;
        }

        const response = await fetch(`${supabaseUrl}/functions/v1/video-metadata`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${supabaseKey}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ url }),
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        console.log(`[DEBUG] getVideoMetadataFromSupabase: Response status: ${response.status}`);

        if (!response.ok) {
          const errorText = await response.text();
          console.error(`[DEBUG] getVideoMetadataFromSupabase: Error response body:`, errorText);
          throw new Error(`HTTP ${response.status}: ${response.statusText} - ${errorText}`);
        }

        const metadata = await response.json();
        console.log(`[DEBUG] getVideoMetadataFromSupabase: Success on attempt ${attempt}, metadata:`, metadata);
        return {
          url,
          video_title: metadata.title || '',
          thumbnail_url: metadata.thumbnailUrl || '',
          video_author_name: metadata.authorName || '',
          video_platform: metadata.platform || '',
          isChecked: false,
        };
      } catch (error) {
        console.error(`[DEBUG] getVideoMetadataFromSupabase: Attempt ${attempt} failed for URL ${url}:`, error);
        
        if (attempt === maxRetries) {
          console.error(`[DEBUG] getVideoMetadataFromSupabase: All attempts failed for URL: ${url}`);
          return null;
        }
        
        // リトライ前に少し待機
        await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
      }
    }
    
    return null;
  };



  // 複数URLの処理
  const processMultipleUrls = async () => {
    if (!multipleUrls.trim()) {
      if (Platform.OS === 'web') {
        window.alert('エラー: URLを入力してください');
      } else {
        Alert.alert('エラー', 'URLを入力してください');
      }
      return;
    }

    setIsProcessing(true);
    const urls = multipleUrls.split('\n').filter(url => url.trim());
    const fetchedVideos: FetchedVideo[] = [];

    for (const url of urls) {
      const trimmedUrl = url.trim();
      if (!trimmedUrl) continue;

      // Instagramの場合：Replitサーバー経由
      if (trimmedUrl.includes('instagram.com')) {
        const metadata = await getInstagramMetadata(trimmedUrl);
        if (metadata) {
          fetchedVideos.push(metadata);
        }
      }
      // YouTubeまたはTikTokの場合：Supabase Edge Function経由
      else if (trimmedUrl.includes('youtube.com/watch') || trimmedUrl.includes('youtu.be') || trimmedUrl.includes('tiktok.com')) {
        const metadata = await getVideoMetadataFromSupabase(trimmedUrl);
        if (metadata) {
          fetchedVideos.push(metadata);
        }
      }
      // その他のURLの場合
      else {
        fetchedVideos.push({
          url: trimmedUrl,
          video_title: `動画 (${new Date().toLocaleDateString('ja-JP')})`,
          thumbnail_url: '',
          video_author_name: '',
          video_platform: 'other',
          isChecked: false,
        });
      }
    }

    setFetchedVideoList(fetchedVideos);
    setIsProcessing(false);
    setShowInputContainer(false);
    setShowConfirmContainer(true);
  };

  // 保存確認の準備
  const prepareConfirmation = () => {
    console.log('[DEBUG] prepareConfirmation: Starting confirmation preparation');
    console.log('[DEBUG] prepareConfirmation: isProcessing:', isProcessing);
    console.log('[DEBUG] prepareConfirmation: fetchedVideoList length:', fetchedVideoList.length);
    
    const selectedVideos = fetchedVideoList.filter(video => video.isChecked);
    console.log('[DEBUG] prepareConfirmation: selectedVideos length:', selectedVideos.length);
    
    if (selectedVideos.length === 0) {
      console.log('[DEBUG] prepareConfirmation: No videos selected, showing error alert');
      if (Platform.OS === 'web') {
        // ブラウザ環境ではシンプルなalert
        if (window.confirm('保存する動画を選択してください')) {
          // 何もしない（エラーメッセージなので）
        }
      } else {
        // モバイル環境ではAlert
        Alert.alert('エラー', '保存する動画を選択してください');
      }
      return;
    }

    const selectedFolder = folders.find(f => f.id === selectedFolderId);
    console.log('[DEBUG] prepareConfirmation: selectedFolder:', selectedFolder?.name);
    
    if (Platform.OS === 'web') {
      // ブラウザ環境ではconfirmを使用
      const message = `選択中の${selectedVideos.length}件の動画を「${selectedFolder?.name || '未分類'}」に保存しますか？`;
      if (window.confirm(message)) {
        console.log('[DEBUG] Browser confirm confirmed, calling saveSelectedVideos');
        saveSelectedVideos();
      }
    } else {
      // モバイル環境ではAlertを使用
      Alert.alert(
        '保存確認',
        `選択中の${selectedVideos.length}件の動画を「${selectedFolder?.name || '未分類'}」に保存しますか？`,
        [
          {
            text: 'いいえ',
            style: 'cancel',
          },
          {
            text: 'はい',
            onPress: () => {
              console.log('[DEBUG] Alert confirmed, calling saveSelectedVideos');
              saveSelectedVideos();
            },
          },
        ]
      );
    }
  };

  // 選択された動画を保存
  const saveSelectedVideos = async () => {
    const selectedVideos = fetchedVideoList.filter(video => video.isChecked);
    
    setIsProcessing(true);

    try {
      for (const video of selectedVideos) {
        await addVideo({
          url: video.url,
          title: video.video_title,
          thumbnailUrl: video.thumbnail_url || 'https://images.pexels.com/photos/1640772/pexels-photo-1640772.jpeg?auto=compress&cs=tinysrgb&w=400',
          source: video.video_platform as any,
          notes: '',
          folderId: selectedFolderId,
          videoTitle: video.video_title,
          videoAuthorName: video.video_author_name,
          videoAuthorIconUrl: null,
        });
      }

      // 保存完了した動画を一覧から削除
      const remainingVideos = fetchedVideoList.filter(video => !video.isChecked);
      setFetchedVideoList(remainingVideos);
      
      // 全選択状態をリセット
      setSelectAll(false);

      // 成功通知
      if (Platform.OS === 'web') {
        // ブラウザ環境ではalert
        window.alert(`${selectedVideos.length}件の動画の保存が完了しました`);
      } else {
        // モバイル環境ではAlert
        Alert.alert('完了', `${selectedVideos.length}件の動画の保存が完了しました`);
      }
      
      // 残りの動画がない場合のみモーダルを閉じる
      if (remainingVideos.length === 0) {
        setTimeout(() => {
          onClose();
        }, 1000);
      }
    } catch (error) {
      if (Platform.OS === 'web') {
        // ブラウザ環境ではalert
        window.alert('動画の保存に失敗しました');
      } else {
        // モバイル環境ではAlert
        Alert.alert('エラー', '動画の保存に失敗しました');
      }
    } finally {
      setIsProcessing(false);
    }
  };

  // 全選択/全解除の切り替え
  const toggleSelectAll = () => {
    const newSelectAll = !selectAll;
    setSelectAll(newSelectAll);
    setFetchedVideoList(prev => 
      prev.map(video => ({ ...video, isChecked: newSelectAll }))
    );
  };

  // 個別動画の選択切り替え
  const toggleVideoSelection = (index: number) => {
    setFetchedVideoList(prev => {
      const updated = [...prev];
      updated[index].isChecked = !updated[index].isChecked;
      return updated;
    });
  };

  // モーダルを閉じる際の確認処理
  const handleCloseModal = () => {
    // 動画一覧が表示されている場合で、未保存の動画がある場合
    if (showConfirmContainer && fetchedVideoList.length > 0) {
      if (Platform.OS === 'web') {
        // ブラウザ環境ではconfirmを使用
        if (window.confirm(`${fetchedVideoList.length}件の未保存の動画があります。閉じますか？`)) {
          onClose();
        }
      } else {
        // モバイル環境ではAlertを使用
        Alert.alert(
          '確認',
          `${fetchedVideoList.length}件の未保存の動画があります。閉じますか？`,
          [
            {
              text: 'キャンセル',
              style: 'cancel',
            },
            {
              text: '閉じる',
              style: 'destructive',
              onPress: () => onClose(),
            },
          ]
        );
      }
    } else {
      // 未保存の動画がない場合は直接閉じる
      onClose();
    }
  };

  // 個別URL入力フォームをクリアする処理
  const handleClearUrls = () => {
    if (Platform.OS === 'web') {
      // ブラウザ環境ではconfirmを使用
      if (window.confirm('入力したURLをすべて削除しますか？')) {
        setMultipleUrls('');
      }
    } else {
      // モバイル環境ではAlertを使用
      Alert.alert(
        '確認',
        '入力したURLをすべて削除しますか？',
        [
          {
            text: 'キャンセル',
            style: 'cancel',
          },
          {
            text: '削除',
            style: 'destructive',
            onPress: () => setMultipleUrls(''),
          },
        ]
      );
    }
  };

  // 再生リストURL入力フォームをクリアする処理
  const handleClearPlaylistUrl = () => {
    if (Platform.OS === 'web') {
      // ブラウザ環境ではconfirmを使用
      if (window.confirm('入力した再生リストURLを削除しますか？')) {
        setPlaylistUrl('');
      }
    } else {
      // モバイル環境ではAlertを使用
      Alert.alert(
        '確認',
        '入力した再生リストURLを削除しますか？',
        [
          {
            text: 'キャンセル',
            style: 'cancel',
          },
          {
            text: '削除',
            style: 'destructive',
            onPress: () => setPlaylistUrl(''),
          },
        ]
      );
    }
  };

  return (
    <>
      <Modal
        animationType="slide"
        transparent={true}
        visible={visible}
        onRequestClose={handleCloseModal}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.header}>
              <Text style={styles.modalTitle}>動画の一括保存</Text>
              <TouchableOpacity onPress={handleCloseModal} style={styles.closeButton}>
                <X size={24} color="#666666" />
              </TouchableOpacity>
            </View>

            {showInputContainer && (
              <ScrollView style={styles.scrollContent}>
                <View style={styles.tabs}>
                  <TouchableOpacity
                    style={[
                      styles.tab,
                      activeTab === 'youtube' && styles.activeTab
                    ]}
                    onPress={() => setActiveTab('youtube')}
                  >
                    <Text style={[
                      styles.tabText,
                      activeTab === 'youtube' && styles.activeTabText
                    ]}>
                      再生リストから
                    </Text>
                  </TouchableOpacity>
                  
                  <TouchableOpacity
                    style={[
                      styles.tab,
                      activeTab === 'other' && styles.activeTab
                    ]}
                    onPress={() => setActiveTab('other')}
                  >
                    <Text style={[
                      styles.tabText,
                      activeTab === 'other' && styles.activeTabText
                    ]}>
                      個別URLから
                    </Text>
                  </TouchableOpacity>
                </View>

                {activeTab === 'youtube' ? (
                  <View style={styles.inputSection}>
                    <View style={styles.urlInputHeader}>
                      <Text style={styles.inputLabel}>YouTube再生リストURL</Text>
                      {playlistUrl.trim() && (
                        <TouchableOpacity onPress={handleClearPlaylistUrl} style={styles.clearButton}>
                          <Text style={styles.clearButtonText}>クリア</Text>
                        </TouchableOpacity>
                      )}
                    </View>
                    <TextInput
                      style={styles.textInput}
                      placeholder="https://youtube.com/playlist?list=..."
                      value={playlistUrl}
                      onChangeText={setPlaylistUrl}
                      multiline={false}
                    />
                    <Button
                      title="再生リストから動画を取得"
                      onPress={processPlaylistUrl}
                      isLoading={isProcessing}
                      style={styles.processButton}
                    />
                  </View>
                ) : (
                  <View style={styles.inputSection}>
                    <View style={styles.urlInputHeader}>
                      <Text style={styles.inputLabel}>動画URL（1行に1つずつ入力）</Text>
                      {multipleUrls.trim() && (
                        <TouchableOpacity onPress={handleClearUrls} style={styles.clearButton}>
                          <Text style={styles.clearButtonText}>クリア</Text>
                        </TouchableOpacity>
                      )}
                    </View>
                    <TextInput
                      style={styles.textAreaInput}
                      placeholder="https://youtube.com/watch?v=...&#10;https://instagram.com/p/...&#10;https://tiktok.com/@user/video/..."
                      value={multipleUrls}
                      onChangeText={setMultipleUrls}
                      multiline={true}
                      numberOfLines={6}
                    />
                    <Button
                      title="入力したURLをすべて処理"
                      onPress={processMultipleUrls}
                      isLoading={isProcessing}
                      style={styles.processButton}
                    />
                  </View>
                )}

                <FolderPicker
                  label="保存先フォルダ"
                  folders={folders}
                  selectedFolderId={selectedFolderId}
                  onValueChange={setSelectedFolderId}
                />
              </ScrollView>
            )}

            {showConfirmContainer && (
              <View style={styles.confirmContainer}>
                <View style={styles.confirmHeader}>
                  <Text style={styles.confirmTitle}>取得した動画一覧</Text>
                  <TouchableOpacity onPress={toggleSelectAll} style={styles.selectAllButton}>
                    {selectAll ? (
                      <CheckSquare size={20} color="#FF9494" />
                    ) : (
                      <Square size={20} color="#666666" />
                    )}
                    <Text style={styles.selectAllText}>全選択</Text>
                  </TouchableOpacity>
                </View>

                <ScrollView style={styles.videoList}>
                  {fetchedVideoList.length === 0 ? (
                    <View style={styles.emptyState}>
                      <Text style={styles.emptyStateText}>すべての動画が保存されました</Text>
                      <Button
                        title="新しい動画を追加"
                        variant="secondary"
                        onPress={() => {
                          setShowConfirmContainer(false);
                          setShowInputContainer(true);
                        }}
                        style={styles.emptyStateButton}
                      />
                    </View>
                  ) : (
                    <>
                      {fetchedVideoList.map((video, index) => (
                        <TouchableOpacity
                          key={index}
                          style={styles.videoItem}
                          onPress={() => toggleVideoSelection(index)}
                        >
                          <View style={styles.videoCheckbox}>
                            {video.isChecked ? (
                              <CheckSquare size={20} color="#FF9494" />
                            ) : (
                              <Square size={20} color="#666666" />
                            )}
                          </View>
                          
                          {video.thumbnail_url ? (
                            <Image source={{ uri: video.thumbnail_url }} style={styles.videoThumbnail} />
                          ) : (
                            <View style={styles.placeholderThumbnail}>
                              <Globe size={24} color="#666666" />
                            </View>
                          )}
                          
                          <View style={styles.videoInfo}>
                            <Text style={styles.videoTitle} numberOfLines={2}>
                              {video.video_title}
                            </Text>
                            {video.video_author_name ? (
                              <Text style={styles.videoAuthor} numberOfLines={1}>
                                {video.video_author_name}
                              </Text>
                            ) : null}
                          </View>
                        </TouchableOpacity>
                      ))}

                      <View style={styles.folderPickerInList}>
                        <FolderPicker
                          label="保存先フォルダ"
                          folders={folders}
                          selectedFolderId={selectedFolderId}
                          onValueChange={setSelectedFolderId}
                        />
                      </View>
                    </>
                  )}
                </ScrollView>

                <View style={styles.confirmFooter}>
                  <Button
                    title="戻る"
                    variant="secondary"
                    onPress={() => {
                      // 未保存の動画がある場合は確認
                      if (fetchedVideoList.length > 0) {
                        if (Platform.OS === 'web') {
                          if (window.confirm(`${fetchedVideoList.length}件の未保存の動画があります。戻りますか？`)) {
                            setShowConfirmContainer(false);
                            setShowInputContainer(true);
                          }
                        } else {
                          Alert.alert(
                            '確認',
                            `${fetchedVideoList.length}件の未保存の動画があります。戻りますか？`,
                            [
                              {
                                text: 'キャンセル',
                                style: 'cancel',
                              },
                              {
                                text: '戻る',
                                style: 'destructive',
                                onPress: () => {
                                  setShowConfirmContainer(false);
                                  setShowInputContainer(true);
                                },
                              },
                            ]
                          );
                        }
                      } else {
                        // 未保存の動画がない場合は直接戻る
                        setShowConfirmContainer(false);
                        setShowInputContainer(true);
                      }
                    }}
                    style={styles.footerButton}
                  />
                  <Button
                    title="選択した動画を保存"
                    onPress={prepareConfirmation}
                    isLoading={isProcessing}
                    style={styles.footerButton}
                  />
                </View>
              </View>
            )}
          </View>
        </View>
      </Modal>


    </>
  );
}

const styles = StyleSheet.create({
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  modalContent: {
    backgroundColor: 'white',
    borderRadius: 20,
    width: '90%',
    height: '80%',
    maxWidth: 600,
    maxHeight: 700,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#EEEEEE',
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1F1F1F',
  },
  closeButton: {
    padding: 4,
  },
  scrollContent: {
    padding: 20,
  },
  tabs: {
    flexDirection: 'row',
    marginBottom: 24,
    borderRadius: 12,
    backgroundColor: '#F5F5F5',
    padding: 4,
  },
  tab: {
    flex: 1,
    paddingVertical: 12,
    alignItems: 'center',
    borderRadius: 8,
  },
  activeTab: {
    backgroundColor: 'white',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 2,
  },
  tabText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#6B6B6B',
  },
  activeTabText: {
    color: '#FF9494',
  },
  inputSection: {
    marginBottom: 24,
  },
  inputLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: '#4B4B4B',
    marginBottom: 8,
  },
  textInput: {
    backgroundColor: '#F5F5F5',
    borderWidth: 1,
    borderColor: '#E0E0E0',
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
    marginBottom: 16,
  },
  textAreaInput: {
    backgroundColor: '#F5F5F5',
    borderWidth: 1,
    borderColor: '#E0E0E0',
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
    height: 120,
    textAlignVertical: 'top',
    marginBottom: 16,
  },
  processButton: {
    marginTop: 8,
  },
  confirmContainer: {
    flex: 1,
  },
  confirmHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#EEEEEE',
  },
  confirmTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1F1F1F',
  },
  selectAllButton: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  selectAllText: {
    fontSize: 14,
    color: '#666666',
    marginLeft: 8,
  },
  videoList: {
    flex: 1,
    padding: 20,
  },
  videoItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#F0F0F0',
  },
  videoCheckbox: {
    marginRight: 12,
  },
  videoThumbnail: {
    width: 60,
    height: 45,
    borderRadius: 6,
    marginRight: 12,
  },
  placeholderThumbnail: {
    width: 60,
    height: 45,
    borderRadius: 6,
    backgroundColor: '#F5F5F5',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  videoInfo: {
    flex: 1,
  },
  videoTitle: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F1F1F',
    marginBottom: 4,
  },
  videoAuthor: {
    fontSize: 12,
    color: '#666666',
  },
  confirmFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    padding: 20,
    borderTopWidth: 1,
    borderTopColor: '#EEEEEE',
    gap: 12,
  },
  footerButton: {
    flex: 1,
  },
  folderPickerInList: {
    padding: 20,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: '#F0F0F0',
    backgroundColor: '#FAFAFA',
  },
  emptyState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 40,
  },
  emptyStateText: {
    fontSize: 16,
    color: '#666666',
    textAlign: 'center',
    marginBottom: 20,
  },
  emptyStateButton: {
    width: 200,
  },
  testButton: {
    backgroundColor: '#FFA500',
    borderColor: '#FFA500',
  },
  urlInputHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  clearButton: {
    backgroundColor: '#FF6B6B',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
  },
  clearButtonText: {
    color: 'white',
    fontSize: 12,
    fontWeight: '500',
  },
});